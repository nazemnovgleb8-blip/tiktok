"""
tunnel.py — публичный туннель для дашборда
Приоритет: ngrok (стабильный, бесплатный постоянный домен) → cloudflared (fallback)
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
        logger.warning(f"Не удалось сохранить URL: {e}")
    if on_ready:
        on_ready(url)


def _find_bin(names: list) -> str | None:
    for n in names:
        for prefix in ["/opt/homebrew/bin/", "/usr/local/bin/", ""]:
            p = prefix + n
            if os.path.exists(p) or "/" not in p:
                try:
                    subprocess.run([p, "--version"],
                                   capture_output=True, timeout=3)
                    return p
                except Exception:
                    pass
    return None


# ── ngrok ─────────────────────────────────────────────────────────────────────

def _run_ngrok(bin_path: str, port: int, on_ready=None):
    """Запускает ngrok и получает URL через его локальный API."""
    cmd = [bin_path, "http", str(port), "--log", "stdout",
           "--log-format", "json"]
    logger.info(f"Запускаю ngrok: {' '.join(cmd)}")

    while True:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            global _tunnel_proc
            _tunnel_proc = proc

            url_found = False
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                logger.debug(f"[ngrok] {line}")

                # Парсим JSON-лог ngrok
                try:
                    obj = json.loads(line)
                    # Ищем URL в разных полях лога
                    url = (obj.get("url") or obj.get("URL") or
                           obj.get("Addr") or "")
                    if not url:
                        msg = obj.get("msg", "")
                        m = re.search(r"https://[^\s\"]+\.ngrok[^\s\"]*", msg)
                        if m:
                            url = m.group(0)
                    if url and url.startswith("https://") and not url_found:
                        url_found = True
                        _save_url(url, on_ready)
                except json.JSONDecodeError:
                    # Текстовый лог — ищем URL напрямую
                    m = re.search(r"https://[^\s]+\.ngrok[^\s]*", line)
                    if m and not url_found:
                        url_found = True
                        _save_url(m.group(0), on_ready)

                # Если URL ещё не нашли — спрашиваем API ngrok
                if not url_found:
                    try:
                        with urllib.request.urlopen(
                            "http://127.0.0.1:4040/api/tunnels", timeout=2
                        ) as r:
                            data = json.loads(r.read())
                            for t in data.get("tunnels", []):
                                u = t.get("public_url", "")
                                if u.startswith("https://"):
                                    url_found = True
                                    _save_url(u, on_ready)
                                    break
                    except Exception:
                        pass

            proc.wait()
            logger.warning("ngrok завершился — перезапуск через 5 сек...")

        except Exception as e:
            logger.error(f"Ошибка ngrok: {e}")

        time.sleep(5)


# ── cloudflared fallback ───────────────────────────────────────────────────────

def _run_cloudflared(bin_path: str, port: int, on_ready=None):
    """Запускает cloudflared quick tunnel."""
    cmd = [bin_path, "tunnel", "--url", f"http://127.0.0.1:{port}"]
    logger.info(f"Запускаю cloudflared: {' '.join(cmd)}")
    url_pattern = re.compile(r"https://[a-z0-9\-]+\.trycloudflare\.com")

    while True:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            global _tunnel_proc
            _tunnel_proc = proc

            for line in proc.stdout:
                line = line.strip()
                if line:
                    logger.debug(f"[cf] {line}")
                m = url_pattern.search(line)
                if m:
                    _save_url(m.group(0), on_ready)

            proc.wait()
            logger.warning("cloudflared завершился — перезапуск через 5 сек...")

        except Exception as e:
            logger.error(f"Ошибка cloudflared: {e}")

        time.sleep(5)


# ── Главная точка входа ────────────────────────────────────────────────────────

def start(port: int = 5001, on_ready=None):
    """Запускает туннель в фоновом потоке. ngrok → cloudflared (fallback)."""

    time.sleep(4)   # даём Flask подняться

    ngrok_bin = _find_bin(["ngrok"])
    cf_bin    = _find_bin(["cloudflared"])

    if not ngrok_bin and not cf_bin:
        logger.warning(
            "Туннель не найден. Установи ngrok:\n"
            "  brew install ngrok/ngrok/ngrok\n"
            "  ngrok config add-authtoken <твой_токен>\n"
            "Дашборд доступен только локально."
        )
        return

    if ngrok_bin:
        runner = lambda: _run_ngrok(ngrok_bin, port, on_ready)
        name   = "ngrok-tunnel"
    else:
        runner = lambda: _run_cloudflared(cf_bin, port, on_ready)
        name   = "cf-tunnel"

    t = threading.Thread(target=runner, daemon=True, name=name)
    t.start()


def stop():
    global _tunnel_proc
    if _tunnel_proc:
        _tunnel_proc.terminate()
        _tunnel_proc = None
        logger.info("Туннель остановлен")
