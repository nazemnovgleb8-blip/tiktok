"""
main.py — Alta Viral Scanner
Точка входа: APScheduler (9:00 каждый день) + Flask dashboard в отдельном потоке.

Запуск:
    python main.py              — нормальный старт
    python main.py --login      — принудительная повторная авторизация TikTok
    python main.py --now        — запустить скан немедленно и выйти
    python main.py --analyze    — только Gemini-анализ последнего скана (без повторного парсинга)
    python main.py --dashboard  — только веб-интерфейс без скана
"""

import argparse
import asyncio
import logging
import logging.handlers
import os
import sys
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import config
import database as db
import dashboard
import tunnel

# ── Логирование ────────────────────────────────────────────────────────────────
# RotatingFileHandler: макс 5 МБ на файл, 3 резервные копии — лог не растёт бесконечно
_log_handler = logging.handlers.RotatingFileHandler(
    "alta_scanner.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-14s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        _log_handler,
    ]
)
logger = logging.getLogger("main")

# ── Глобальный флаг: идёт ли скан прямо сейчас ────────────────────────────────
_scan_running = threading.Event()


# ──────────────────────────────────────────────────────────────────────────────
#  ОСНОВНАЯ ФУНКЦИЯ СКАНА
# ──────────────────────────────────────────────────────────────────────────────

def run_full_scan(need_login: bool = False):
    """
    Полный цикл:
      scanner → analyzer → notifier → сохранение в БД
    Защищён от параллельного запуска через _scan_running.
    """
    if _scan_running.is_set():
        logger.warning("Скан уже запущен — пропускаю повторный запуск")
        return

    _scan_running.set()
    scan_id = db.start_scan()
    logger.info(f"══ Начало скана #{scan_id} ══")

    try:
        cfg = config.load()

        # ── 1. Сканирование TikTok ─────────────────────────────────────────
        from scanner import run_scan

        def on_progress(msg):
            logger.info(f"[scanner] {msg}")

        logger.info("▶ Запускаю TikTok scanner...")
        all_videos, filtered = asyncio.run(
            run_scan(cfg, on_progress=on_progress, need_login=need_login)
        )

        logger.info(
            f"Scanner завершён: всего={len(all_videos)}, "
            f"Score≥{cfg.get('min_score', 50)}x: {len(filtered)}"
        )

        if not filtered:
            logger.warning("Нет видео прошедших фильтр — скан завершён без отправки")
            db.finish_scan(scan_id, len(all_videos), 0)
            return

        # ── 2. Сохраняем сырые данные в БД ────────────────────────────────
        db.save_videos(scan_id, filtered)

        # ── 3. Gemini-анализ топ-N ─────────────────────────────────────────
        from analyzer import analyze_videos

        logger.info("▶ Запускаю Gemini-анализ...")
        enriched = asyncio.run(analyze_videos(filtered, cfg))

        # Обновляем Gemini-поля в БД
        for v in enriched:
            if v.get("gemini_done"):
                db.update_gemini(
                    url=v["url"],
                    relevance=v.get("relevance", 0),
                    hook=v.get("hook", ""),
                    adaptation=v.get("adaptation", ""),
                    category=v.get("category", "вирал"),
                    why_viral=v.get("why_viral", ""),
                    priority=v.get("priority", "средний"),
                )

        logger.info("Gemini-анализ завершён")

        # ── 4. Финализируем скан в БД ──────────────────────────────────────
        stats = db.get_stats(scan_id)
        db.finish_scan(scan_id, len(all_videos), len(filtered))

        # ── 5. Instant-алерты (Score ≥ 1000x) ─────────────────────────────
        from notifier import check_and_send_alerts

        logger.info("▶ Проверяю алерты 1000x+...")
        check_and_send_alerts(enriched, cfg)

        # ── 6. Утренний дайджест ───────────────────────────────────────────
        from notifier import send_daily_digest

        scan_stats = {
            "total_scraped":  len(all_videos),
            "total_relevant": len(filtered),
            "max_score":      stats.get("max_score", 0) or 0,
            "ultra":          stats.get("ultra", 0) or 0,
        }

        logger.info("▶ Отправляю дайджест в Telegram...")
        send_daily_digest(enriched, scan_stats, cfg, scan_id=scan_id)

        logger.info(f"══ Скан #{scan_id} завершён успешно ══")

        # Очистка временных файлов (скрины, trace и т.п.)
        _cleanup_temp_files()

        # Синхронизируем данные на Railway (только локально)
        if not os.environ.get("RAILWAY_ENVIRONMENT"):
            _sync_to_remote(scan_id, cfg)
            _git_push()

    except Exception as e:
        logger.exception(f"Ошибка скана #{scan_id}: {e}")
        db.fail_scan(scan_id, str(e))
    finally:
        _scan_running.clear()


# ──────────────────────────────────────────────────────────────────────────────
#  ЗАПУСК ДАШБОРДА В ФОНЕ
# ──────────────────────────────────────────────────────────────────────────────

def _start_dashboard(cfg):
    """Запускает Flask + Cloudflare туннель в отдельных daemon-потоках."""
    port = cfg.get("dashboard_port", 5001)

    def _scan_callback():
        """Вызывается из дашборда при нажатии «Запустить скан»."""
        t = threading.Thread(target=run_full_scan, daemon=True, name="manual-scan")
        t.start()

    t = threading.Thread(
        target=dashboard.start,
        kwargs={"scan_cb": _scan_callback, "host": "0.0.0.0", "port": port},
        daemon=True,
        name="dashboard",
    )
    t.start()
    logger.info(f"Дашборд запущен на http://localhost:{port}")

    # Туннель нужен только локально — на Railway есть публичный URL из env
    import os as _os
    if not _os.environ.get("RAILWAY_ENVIRONMENT"):
        def _on_tunnel_ready(url: str):
            logger.info(f"🌐 Дашборд публично доступен: {url}")
        tunnel.start(port=port, on_ready=_on_tunnel_ready)


# ──────────────────────────────────────────────────────────────────────────────
#  ПЛАНИРОВЩИК
# ──────────────────────────────────────────────────────────────────────────────

def _start_scheduler(cfg):
    hour   = cfg.get("schedule_hour", 9)
    minute = cfg.get("schedule_minute", 0)

    scheduler = BackgroundScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        run_full_scan,
        trigger=CronTrigger(hour=hour, minute=minute),
        id="daily_scan",
        name="Daily Viral Scan",
        replace_existing=True,
        misfire_grace_time=3600,  # если пропустили — запустить в течение часа
    )
    scheduler.start()
    logger.info(f"Планировщик: скан каждый день в {hour:02d}:{minute:02d} МСК")
    return scheduler


# ──────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────

def _restore_session(cfg: dict):
    """Восстанавливает tiktok_session.json из БД или env при каждом старте."""
    import base64
    session_path = cfg.get("session_file", "tiktok_session.json")
    if os.path.exists(session_path):
        return  # файл уже есть

    # 1. Пробуем из БД
    b64 = db.kv_get("tiktok_session_b64")
    if not b64:
        # 2. Пробуем из env
        b64 = os.environ.get("TIKTOK_SESSION_B64", "").strip()
    if b64:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(session_path)), exist_ok=True)
            with open(session_path, "wb") as f:
                f.write(base64.b64decode(b64))
            logger.info("✓ TikTok сессия восстановлена")
        except Exception as e:
            logger.warning(f"Не удалось восстановить сессию: {e}")
    else:
        logger.warning("Сессия TikTok не найдена — загрузи через Настройки дашборда")


def main():
    parser = argparse.ArgumentParser(description="Alta Viral Scanner")
    parser.add_argument("--login",     action="store_true",
                        help="Принудительная повторная авторизация TikTok")
    parser.add_argument("--now",       action="store_true",
                        help="Запустить скан немедленно (блокирующий режим)")
    parser.add_argument("--analyze",   action="store_true",
                        help="Только Gemini-анализ последнего скана без повторного парсинга")
    parser.add_argument("--dashboard", action="store_true",
                        help="Только веб-интерфейс, без автозапуска скана")
    args = parser.parse_args()

    # Инициализация БД
    db.init()
    cfg = config.load()

    # Восстанавливаем TikTok сессию: сначала из БД, потом из env
    _restore_session(cfg)

    logger.info("━" * 60)
    logger.info("  Alta Viral Scanner  |  стартуем...")
    logger.info("━" * 60)

    # ── Режим: только Gemini-анализ последнего скана ──────────────────────
    if args.analyze:
        _run_analyze_only(cfg)
        return

    # ── Режим: только запустить скан сейчас ──────────────────────────────
    if args.now:
        logger.info("Режим --now: запускаю скан немедленно")
        run_full_scan(need_login=args.login)
        return

    # ── Запускаем дашборд ─────────────────────────────────────────────────
    _start_dashboard(cfg)

    if args.dashboard:
        logger.info("Режим --dashboard: планировщик отключён")
        _keep_alive()
        return

    # ── Запускаем планировщик ─────────────────────────────────────────────
    scheduler = _start_scheduler(cfg)

    # Проверяем есть ли незавершённый скан сегодня
    latest_any = _get_latest_any_scan()
    latest_done = db.get_latest_scan()
    today = datetime.now().strftime("%Y-%m-%d")

    if latest_any and latest_any.get("started_at", "")[:10] == today and latest_any.get("status") == "running":
        # Есть незавершённый скан сегодня — продолжаем с Gemini
        logger.info("Найден незавершённый скан — запускаю только Gemini-анализ")
        t = threading.Thread(target=_run_analyze_only, args=(cfg,), daemon=True, name="resume-analyze")
        t.start()
    elif not latest_done or latest_done.get("finished_at", "")[:10] != today:
        logger.info("Сегодня скан ещё не завершался — стартую немедленно")
        t = threading.Thread(
            target=run_full_scan,
            kwargs={"need_login": False},
            daemon=True, name="startup-scan",
        )
        t.start()

    _keep_alive(scheduler)


def _get_latest_any_scan() -> dict | None:
    """Возвращает последний скан в любом статусе."""
    import sqlite3
    try:
        conn = db.get_conn()
        row = conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def _run_analyze_only(cfg: dict):
    """Запускает только Gemini-анализ для последнего скана у которого есть видео."""
    # Ищем последний скан с видео (не обязательно завершённый)
    conn = db.get_conn()
    row = conn.execute("""
        SELECT s.* FROM scans s
        WHERE (SELECT COUNT(*) FROM videos v WHERE v.scan_id = s.id) > 0
        ORDER BY s.id DESC LIMIT 1
    """).fetchone()
    conn.close()

    if not row:
        logger.warning("Нет сканов с видео в базе — нечего анализировать")
        return

    scan = dict(row)
    scan_id = scan["id"]
    _count_conn = db.get_conn()
    total_videos = _count_conn.execute(
        "SELECT COUNT(*) FROM videos WHERE scan_id=?", (scan_id,)
    ).fetchone()[0]
    _count_conn.close()
    logger.info(f"Найден скан #{scan_id} с {total_videos} видео — запускаю Gemini-анализ...")

    videos = db.get_scan_videos(scan_id, limit=500)
    if not videos:
        logger.warning("Нет видео в этом скане")
        return

    # Сортируем по score, берём топ
    videos.sort(key=lambda x: x.get("score", 0), reverse=True)

    try:
        from analyzer import analyze_videos
        enriched = asyncio.run(analyze_videos(videos, cfg))

        for v in enriched:
            if v.get("gemini_done"):
                db.update_gemini(
                    url=v["url"],
                    relevance=v.get("relevance", 0),
                    hook=v.get("hook", ""),
                    adaptation=v.get("adaptation", ""),
                    category=v.get("category", "вирал"),
                    why_viral=v.get("why_viral", ""),
                    priority=v.get("priority", "средний"),
                )

        # Финализируем скан
        total = scan.get("total_scraped", len(videos))
        db.finish_scan(scan_id, total, len(videos))

        # Отправляем дайджест
        from notifier import send_daily_digest, check_and_send_alerts
        stats = db.get_stats(scan_id)
        scan_stats = {
            "total_scraped":  total,
            "total_relevant": len(videos),
            "max_score":      stats.get("max_score", 0) or 0,
            "ultra":          stats.get("ultra", 0) or 0,
        }
        check_and_send_alerts(enriched, cfg)
        send_daily_digest(enriched, scan_stats, cfg, scan_id=scan_id)
        logger.info("✅ Анализ и дайджест завершены!")

        # Синхронизируем с Railway (только локально)
        if not os.environ.get("RAILWAY_ENVIRONMENT"):
            _cleanup_temp_files()
            _sync_to_remote(scan_id, cfg)
            _git_push()

    except Exception as e:
        logger.exception(f"Ошибка анализа: {e}")


def _cleanup_temp_files():
    """Удаляет временные файлы Playwright (HAR, trace, скриншоты) после скана."""
    import glob, shutil
    dir_ = os.path.dirname(os.path.abspath(__file__))
    patterns = [
        os.path.join(dir_, "*.png"),
        os.path.join(dir_, "*.jpg"),
        os.path.join(dir_, "*.jpeg"),
        os.path.join(dir_, "trace.zip"),
        os.path.join(dir_, "*.har"),
    ]
    removed = 0
    for pat in patterns:
        for f in glob.glob(pat):
            try:
                os.remove(f)
                removed += 1
                logger.debug(f"Удалён временный файл: {f}")
            except Exception:
                pass
    if removed:
        logger.info(f"🧹 Очищено временных файлов: {removed}")


def _sync_to_remote(scan_id: int, cfg: dict):
    """
    Отправляет данные завершённого скана на Railway (POST /api/ingest).
    Запускается только локально — на Railway синхронизация не нужна.
    """
    import requests as req_lib

    dashboard_url = cfg.get("dashboard_url", "").strip().rstrip("/")
    if not dashboard_url or "localhost" in dashboard_url:
        logger.debug("Синхронизация: dashboard_url не задан или локальный — пропускаю")
        return

    sync_token = cfg.get("sync_token", "").strip()

    try:
        scan   = db.get_scan_by_id(scan_id)
        if not scan:
            logger.warning(f"Синхронизация: скан #{scan_id} не найден в БД")
            return

        videos = db.get_scan_videos(scan_id, limit=500)

        headers = {"Content-Type": "application/json"}
        if sync_token:
            headers["Authorization"] = f"Bearer {sync_token}"

        resp = req_lib.post(
            f"{dashboard_url}/api/ingest",
            json={"scan": scan, "videos": videos},
            headers=headers,
            timeout=60,
        )
        if resp.ok:
            data = resp.json()
            logger.info(
                f"✅ Синхронизация на Railway: "
                f"скан #{data.get('scan_id')}, {data.get('videos')} видео → {dashboard_url}"
            )
        else:
            logger.warning(f"Синхронизация не удалась: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Ошибка синхронизации: {e}")


def _git_push():
    """Авто-пуш изменений в GitHub после скана — Railway задеплоится автоматически."""
    import subprocess
    try:
        dir_ = os.path.dirname(os.path.abspath(__file__))
        subprocess.run(["git", "-C", dir_, "add", "-A"], timeout=30, check=False)
        subprocess.run(
            ["git", "-C", dir_, "commit", "-m",
             f"auto: скан завершён {datetime.now().strftime('%d.%m %H:%M')}"],
            timeout=30, check=False
        )
        result = subprocess.run(
            ["git", "-C", dir_, "push"],
            timeout=60, check=False, capture_output=True, text=True
        )
        if result.returncode == 0:
            logger.info("✅ Изменения запушены в GitHub — Railway задеплоится автоматически")
        else:
            logger.warning(f"Git push не удался: {result.stderr[:200]}")
    except Exception as e:
        logger.warning(f"Авто-пуш не удался: {e}")


def _keep_alive(scheduler=None):
    """Держит главный поток живым, ждёт Ctrl+C."""
    logger.info("Нажми Ctrl+C для остановки")
    try:
        while True:
            import time
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановка...")
        if scheduler:
            scheduler.shutdown()


if __name__ == "__main__":
    main()
