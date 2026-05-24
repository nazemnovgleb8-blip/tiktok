"""
notifier.py — Telegram уведомления
Минималистичный дайджест: чистый текст, минимум эмодзи, максимум читабельности
"""
import logging
import requests

logger = logging.getLogger("notifier")

ALERT_THRESHOLD = 5000


def _send(token: str, chat_id: str, text: str, disable_preview: bool = True):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        resp = requests.post(url, json={
            "chat_id":                  chat_id,
            "text":                     chunk,
            "parse_mode":               "HTML",
            "disable_web_page_preview": disable_preview,
        }, timeout=15)
        if not resp.ok:
            logger.error(f"Telegram ошибка: {resp.status_code} {resp.text}")


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}М"
    if n >= 1_000:
        return f"{n/1_000:.0f}К"
    return str(n)


def _cat(cat: str) -> str:
    return {
        "брендинг":   "брендинг",
        "сайты":      "сайты",
        "ии-контент": "ии-контент",
        "вирал":      "вирал",
    }.get(cat, "вирал")


def send_daily_digest(videos: list[dict], scan_stats: dict, cfg: dict):
    token   = cfg.get("telegram_bot_token", "")
    chat_id = cfg.get("telegram_chat_id", "")
    if not token or not chat_id:
        logger.warning("Telegram не настроен — дайджест не отправлен")
        return

    from datetime import date
    today = date.today().strftime("%d.%m.%Y")

    total   = scan_stats.get("total_relevant", 0)
    ultra   = scan_stats.get("ultra", 0)
    best    = scan_stats.get("max_score", 0)

    dashboard_url = cfg.get("dashboard_url", "").strip()
    if not dashboard_url:
        port = cfg.get("dashboard_port", 5001)
        dashboard_url = f"http://localhost:{port}"

    lines = []

    # ── Шапка ─────────────────────────────────────────────────────────────────
    lines.append(f"<b>Alta Viral Scout</b>  ·  {today}")
    lines.append(
        f"Видео: <b>{total}</b>  ·  сверхвирал 500x+: <b>{ultra}</b>  ·  рекорд: <b>{best:.0f}x</b>"
    )

    # ── Топ-3 ─────────────────────────────────────────────────────────────────
    lines.append("")
    lines.append("─────────────────────────────")
    lines.append("<b>Топ-3 — копировать сегодня</b>")
    lines.append("─────────────────────────────")

    for i, v in enumerate(videos[:3], 1):
        score  = v.get("score", 0)
        views  = _fmt(v.get("views", 0))
        subs   = _fmt(v.get("followers", 0))
        source = v.get("source", "")
        url    = v.get("url", "")
        cat    = _cat(v.get("category", "вирал"))
        hook   = (v.get("gemini_hook") or v.get("hook", "")).strip()
        adapt  = (v.get("gemini_adaptation") or v.get("adaptation", "")).strip()

        lines.append("")
        # Строка 1: номер, счёт, категория
        lines.append(f"<b>#{i}  {score:.0f}x</b>  ·  {cat}")
        # Строка 2: метрики
        lines.append(f"{views} просм  ·  {subs} подп  ·  {source}")
        # Строка 3: хук (если есть)
        if hook:
            hook_short = hook[:130] + "…" if len(hook) > 130 else hook
            lines.append(f"<i>{hook_short}</i>")
        # Строка 4: адаптация (если есть)
        if adapt:
            adapt_short = adapt[:150] + "…" if len(adapt) > 150 else adapt
            lines.append(adapt_short)
        lines.append(f'<a href="{url}">Смотреть →</a>')

    # ── Топ 4–10 (компактно) ──────────────────────────────────────────────────
    rest = videos[3:10]
    if rest:
        lines.append("")
        lines.append("─────────────────────────────")
        lines.append("<b>Топ 4–10</b>")
        lines.append("─────────────────────────────")
        lines.append("")
        for i, v in enumerate(rest, 4):
            score  = v.get("score", 0)
            views  = _fmt(v.get("views", 0))
            source = v.get("source", "")
            url    = v.get("url", "")
            lines.append(
                f"<b>#{i}</b>  ·  {score:.0f}x  ·  {views}  ·  {source}"
                f'  ·  <a href="{url}">→</a>'
            )

    # ── Футер ─────────────────────────────────────────────────────────────────
    lines.append("")
    lines.append("─────────────────────────────")
    lines.append(
        f'<a href="{dashboard_url}">Полный отчёт с анализом →</a>'
        f"  ·  следующий скан в 9:00"
    )

    _send(token, chat_id, "\n".join(lines))
    logger.info(f"Дайджест отправлен ({len(videos[:10])} видео, ссылка: {dashboard_url})")


def check_and_send_alerts(videos: list[dict], cfg: dict):
    """Все находки Score >= порога — одним компактным сообщением."""
    token   = cfg.get("telegram_bot_token", "")
    chat_id = cfg.get("telegram_chat_id", "")
    if not token or not chat_id:
        return

    hits = [v for v in videos if v.get("score", 0) >= ALERT_THRESHOLD]
    if not hits:
        return

    hits.sort(key=lambda x: x.get("score", 0), reverse=True)

    dashboard_url = cfg.get("dashboard_url", "").strip()
    if not dashboard_url:
        port = cfg.get("dashboard_port", 5001)
        dashboard_url = f"http://localhost:{port}"

    lines = [
        f"<b>Сверхвирал  ·  {len(hits)} находок  ·  {ALERT_THRESHOLD:,}x+</b>",
        "",
    ]
    for v in hits:
        score  = v.get("score", 0)
        views  = _fmt(v.get("views", 0))
        subs   = _fmt(v.get("followers", 0))
        source = v.get("source", "")
        url    = v.get("url", "")
        author = v.get("author", "")
        lines.append(
            f"<b>{score:.0f}x</b>  ·  @{author}  ·  {source}"
        )
        lines.append(
            f"{views} просм  ·  {subs} подп  ·  "
            f'<a href="{url}">смотреть →</a>'
        )
        lines.append("")

    lines.append(f'<a href="{dashboard_url}">Дашборд →</a>')

    _send(token, chat_id, "\n".join(lines))
    logger.info(f"Алерт: {len(hits)} находок Score≥{ALERT_THRESHOLD}x")
