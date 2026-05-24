"""
config.py — загрузка и сохранение настроек из config.json
"""
import json
import os

DIR = os.path.dirname(os.path.abspath(__file__))

IS_RAILWAY = bool(os.environ.get("RAILWAY_ENVIRONMENT"))

# На Railway конфиг и БД хранятся в /data если volume примонтирован,
# иначе — рядом со скриптом (в контейнере данные живут до следующего деплоя)
if IS_RAILWAY:
    DATA_DIR = "/data" if os.path.ismount("/data") else DIR
else:
    DATA_DIR = DIR

CONFIG_FILE  = os.path.join(DATA_DIR, "config.json")
_CONFIG_SEED = os.path.join(DIR, "config.example.json")  # шаблон из репо

DEFAULT = {
    # ── TikTok источники ──────────────────────────────────────
    "hashtags": [
        "viral", "ai", "ИИ", "нейросети",
        "brandtransformation", "logodesign", "logoreveal",
        "brandreveal", "rebranding", "брендинг",
        "айдентика", "упаковкабизнеса", "нейросеть"
    ],
    "search_queries": [
        "brand transformation",
        "logo reveal",
        "AI design",
        "ИИ дизайн",
        "логотип до после",
        "ребрендинг бизнес",
        "сайт для бизнеса"
    ],
    "seed_accounts": [
        "iron_deluxe",
        "kleneldesign1",
        "aigenerateeee",
        "bealopes.svg"
    ],

    # ── Фильтрация ────────────────────────────────────────────
    "min_score": 10,
    "target_per_source": 100,       # сколько видео брать с каждого источника
    "gemini_top_n": 50,             # сколько топ-видео отправлять в Gemini

    # ── API ключи ─────────────────────────────────────────────
    "gemini_api_key": "",
    "telegram_bot_token": "",
    "telegram_chat_id": "",

    # ── Расписание ────────────────────────────────────────────
    "schedule_hour": 8,
    "schedule_minute": 0,

    # ── Браузер ───────────────────────────────────────────────
    "chrome_path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "profile_dir": os.path.expanduser(
        "~/Library/Application Support/Google/Chrome/TikTokBot"
    ),
    "session_file": os.path.join(DATA_DIR, "tiktok_session.json"),

    # ── Веб-дашборд ───────────────────────────────────────────
    "dashboard_port": int(os.environ.get("PORT", 5001)),
    "dashboard_host": "0.0.0.0",
    "dashboard_url":  os.environ.get("RAILWAY_STATIC_URL", ""),
}


def load() -> dict:
    # На Railway при первом старте копируем seed-конфиг из репо в /data
    if IS_RAILWAY and not os.path.exists(CONFIG_FILE):
        if os.path.exists(_CONFIG_SEED):
            import shutil
            os.makedirs(DATA_DIR, exist_ok=True)
            shutil.copy(_CONFIG_SEED, CONFIG_FILE)

    if not os.path.exists(CONFIG_FILE):
        save(DEFAULT)
        return DEFAULT.copy()

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Добавляем новые ключи из DEFAULT если их нет
    updated = False
    for k, v in DEFAULT.items():
        if k not in data:
            data[k] = v
            updated = True

    # На Railway порт и URL берём из env
    if IS_RAILWAY:
        port = int(os.environ.get("PORT", data.get("dashboard_port", 5001)))
        data["dashboard_port"] = port
        data["dashboard_host"] = "0.0.0.0"
        # Railway даёт RAILWAY_PUBLIC_DOMAIN = "myapp.up.railway.app"
        for rkey in ("RAILWAY_PUBLIC_DOMAIN", "RAILWAY_SERVICE_DOMAIN",
                     "RAILWAY_STATIC_URL"):
            railway_domain = os.environ.get(rkey, "").strip()
            if railway_domain:
                data["dashboard_url"] = (
                    railway_domain if railway_domain.startswith("http")
                    else f"https://{railway_domain}"
                )
                break
        data["session_file"] = os.path.join(DATA_DIR, "tiktok_session.json")
        updated = True

    # Переменные окружения всегда перекрывают config.json (удобно для Railway)
    _env_map = {
        "GEMINI_API_KEY":      "gemini_api_key",
        "TELEGRAM_BOT_TOKEN":  "telegram_bot_token",
        "TELEGRAM_CHAT_ID":    "telegram_chat_id",
        "PROXY":               "proxy",
        "DASHBOARD_URL":       "dashboard_url",
        "MIN_SCORE":           "min_score",
        "MIN_VIEWS":           "min_views",
    }
    for env_key, cfg_key in _env_map.items():
        val = os.environ.get(env_key, "").strip()
        if val:
            data[cfg_key] = int(val) if cfg_key in ("min_score", "min_views") else val

    if updated:
        save(data)
    return data


def save(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def restore_session_from_env():
    """
    Если задана TIKTOK_SESSION_B64 — декодирует и сохраняет сессию в /data.
    Вызывается при старте приложения.
    """
    b64 = os.environ.get("TIKTOK_SESSION_B64", "").strip()
    if not b64:
        return
    import base64
    session_path = os.path.join(DATA_DIR, "tiktok_session.json")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        data = base64.b64decode(b64)
        with open(session_path, "wb") as f:
            f.write(data)
    except Exception as e:
        import logging
        logging.getLogger("config").warning(f"Не удалось восстановить сессию из env: {e}")
