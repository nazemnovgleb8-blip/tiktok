"""
config.py — загрузка и сохранение настроек из config.json
"""
import json
import os

DIR = os.path.dirname(os.path.abspath(__file__))

# На Railway данные хранятся в /data (постоянный volume)
# Локально — рядом со скриптом
IS_RAILWAY = bool(os.environ.get("RAILWAY_ENVIRONMENT"))
DATA_DIR   = "/data" if IS_RAILWAY else DIR

CONFIG_FILE  = os.path.join(DATA_DIR, "config.json")
_CONFIG_SEED = os.path.join(DIR, "config.json")  # исходный файл в репо

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
        railway_url = os.environ.get("RAILWAY_STATIC_URL", "")
        if railway_url:
            data["dashboard_url"] = f"https://{railway_url}"
        data["session_file"] = os.path.join(DATA_DIR, "tiktok_session.json")
        updated = True

    if updated:
        save(data)
    return data


def save(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
