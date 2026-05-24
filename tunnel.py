"""
tunnel.py — публичный туннель для локального дашборда

Приоритет:
  1. DASHBOARD_URL env-var (ручной URL — самый надёжный)
  2. ngrok (стабильный, бесплатный постоянный домен)
  3. Инструкция пользователю (cloudflared убран — ненадёжен)

На Railway туннель не нужен — там уже есть публичный HTTPS URL.
"""
import re
import subprocess
import threading
import logging
import os
import time
import urllib.request
import json

import config as cfg_module

logger = logging.getLogger("tunnel")

_tunnel_url  = ""
_tunnel_proc = None


def get_url() -> str:
    return _tunnel_url


def _save_url(url: str, on_ready=None):
    global _tunnel_url
    if url == _tunnel_url:
        return
    _tunnel_url = url
    logger.info(f"✅ Туннель активен: {url}")
    try:
        c = cfg_module.load()
        c["dashboard_url"] = url
        cfg_module.save(c)
    except Exception as e:
        logger.warning(f"Не удалось сохранить URL туннеля: {e}")
    if on_ready:
        on_ready(url)


def _find_ngrok() -> str | None:
    """Ищет ngrok в стандартных путях."""
    candidates = [
        "/opt/homebrew/bin/ngrok",
        "/usr/local/bin/ngrok",
        os.path.expanduser("~/bin/ngrok"),
        "ngrok",  # если в PATH
    ]
    for path in candidates:
        try:
            result = subprocess.run(
                [path, "version"],
                capture_output=True, timeout=3
            )
            if result.returncode == 0:
                return path
        except Exception:
            pass
    return None


def _poll_ngrok_api(on_ready=None) -> bool:
    """Опрашивает ngrok API на localhost:4040, возвращает True если нашёл URL."""
    for _ in range(20):   # до 10 секунд
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:4040/api/tunnels", timeout=1
            ) as r:
                data = json.loads(r.read())
                for t in data.get("tunnels", []):
                    u = t.get("public_url", "")
                    if u.startswith("https://"):
                        _save_url(u, on_ready)
                        return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _run_ngrok(bin_path: str, port: int, on_ready=None):
    """Запускает ngrok и получает публичный URL через API (ngrok v3+)."""
    cmd = [bin_path, "http", str(port)]
    logger.info(f"Запускаю ngrok на порту {port}...")

    while True:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            global _tunnel_proc
            _tunnel_proc = proc

            # Ждём пока ngrok поднимет туннель и опрашиваем API
            time.sleep(2)
            if _poll_ngrok_api(on_ready):
                # Держим процесс живым
                proc.wait()
            else:
                logger.warning("ngrok запустился, но URL не получен через API за 10 сек")
                proc.wait()

            logger.warning("ngrok завершился — перезапуск через 5 сек...")

        except Exception as e:
            logger.error(f"Ошибка ngrok: {e}")

        time.sleep(5)


def start(port: int = 5001, on_ready=None):
    """
    Запускает туннель в фоновом потоке.
    На Railway — не нужен (там уже публичный URL).
    """
    # Если задан ручной URL — туннель не нужен
    manual_url = os.environ.get("DASHBOARD_URL", "").strip()
    if manual_url:
        logger.info(f"DASHBOARD_URL задан вручную: {manual_url}")
        _save_url(manual_url, on_ready)
        return

    time.sleep(4)  # даём Flask подняться

    ngrok_bin = _find_ngrok()
    if ngrok_bin:
        t = threading.Thread(
            target=_run_ngrok,
            args=(ngrok_bin, port, on_ready),
            daemon=True, name="ngrok-tunnel"
        )
        t.start()
        return

    # ngrok не найден — объясняем как установить
    logger.warning(
        "\n" + "━" * 55 +
        "\n  Дашборд запущен локально, но публичный URL недоступен." +
        "\n  Чтобы Telegram-ссылки работали:" +
        "\n" +
        "\n  Вариант 1 — ngrok (рекомендуется):" +
        "\n    brew install ngrok/ngrok/ngrok" +
        "\n    ngrok config add-authtoken <твой_токен>" +
        "\n    (регистрация бесплатна: https://ngrok.com)" +
        "\n" +
        "\n  Вариант 2 — вручную в настройках дашборда:" +
        "\n    Настройки → 'URL дашборда' → вставь любой публичный URL" +
        "\n    (напр. Railway URL: https://tiktok-production-xxxx.up.railway.app)" +
        "\n" + "━" * 55
    )

    # Ставим localhost как fallback чтобы ссылки хотя бы были
    local_url = f"http://localhost:{port}"
    _save_url(local_url, on_ready)


def stop():
    global _tunnel_proc
    if _tunnel_proc:
        _tunnel_proc.terminate()
        _tunnel_proc = None
        logger.info("Туннель остановлен")
