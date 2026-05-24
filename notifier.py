"""
notifier.py — Telegram уведомления
Единый формат для всех видео: счёт + метрики + хук + адаптация + ссылка
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


def _get_dashboard_url(cfg: dict) -> str:
    """Возвращает актуальный URL дашборда — сначала из живого туннеля."""
    # Сначала пробуем live-URL от запущенного туннеля
    try:
        import tunnel
        live = tunnel.get_url()
        if live and live.startswith("http"):
            return live
    except Exception:
        pass
    # Fallback: Railway env → config
    import os
    railway = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
    if railway:
        return f"https://{railway}"
    url = cfg.get("dashboard_url", "").strip()
    if url:
        return url
    port = cfg.get("dashboard_port", 5001)
    return f"http://localhost:{port}"


def _fmt_video(i: int, v: dict, show_source: bool = True) -> list[str]:
    """Форматирует одно видео в строки Telegram."""
    score  = v.get("score", 0)
    views  = _fmt(v.get("views", 0))
    subs   = _fmt(v.get("followers", 0))
    source = v.get("source", "")
    url    = v.get("url", "")
    cat    = _cat(v.get("category", "вирал"))
    hook   = (v.get("gemini_hook") or v.get("hook", "")).strip()
    adapt  = (v.get("gemini_adaptation") or v.get("adaptation", "")).strip()

    lines = []
    lines.append("")

    # Строка 1: номер · счёт · категория
    lines.append(f"<b>#{i}  {score:.0f}x</b>  ·  {cat}")

    # Строка 2: метрики + источник
    meta = f"{views} просм  ·  {subs} подп"
    if show_source and source:
        # Укорачиваем длинный source
        src_short = source.replace("search:", "").replace("account:", "@").replace("fyp", "FYP")
        meta += f"  ·  {src_short}"
    lines.append(meta)

    # Строка 3: хук (курсив)
    if hook:
        hook_short = hook[:160] + "…" if len(hook) > 160 else hook
        lines.append(f"<i>{hook_short}</i>")

    # Строка 4: адаптация
    if adapt:
        adapt_short = adapt[:180] + "…" if len(adapt) > 180 else adapt
        lines.append(adapt_short)

    lines.append(f'<a href="{url}">Смотреть →</a>')
    return lines


def send_daily_digest(videos: list[dict], scan_stats: dict, cfg: dict, scan_id: int = None):
    token   = cfg.get("telegram_bot_token", "")
    chat_id = cfg.get("telegram_chat_id", "")
    if not token or not chat_id:
        logger.warning("Telegram не настроен — дайджест не отправлен")
        return

    from datetime import date
    today = date.today().strftime("%d.%m.%Y")

    # ── Фильтр по минимальным просмотрам ──────────────────────────────────────
    min_views  = cfg.get("min_views", 50_000)
    MIN_DIGEST = 10  # минимум видео в дайджесте всегда

    filtered = [v for v in videos if v.get("views", 0) >= min_views]

    # Если прошло меньше MIN_DIGEST — добираем лучшие по score из остальных
    if len(filtered) < MIN_DIGEST:
        already = {v["url"] for v in filtered}
        extras  = [v for v in videos if v["url"] not in already]
        need    = MIN_DIGEST - len(filtered)
        filtered = filtered + extras[:need]
        logger.info(f"В дайджесте: {len(filtered)} видео ({len(filtered)-need} с {_fmt(min_views)}+ просмотрами + {need} добрали)")

    total   = scan_stats.get("total_relevant", 0)
    ultra   = scan_stats.get("ultra", 0)
    best    = scan_stats.get("max_score", 0)

    base_url = _get_dashboard_url(cfg)
    # Ссылка ведёт на конкретный скан если передан scan_id, иначе на главную
    if scan_id:
        report_url = f"{base_url.rstrip('/')}/scan/{scan_id}"
    else:
        report_url = base_url

    lines = []

    # ── Шапка ─────────────────────────────────────────────────────────────────
    lines.append(f"<b>Alta Viral Scout</b>  ·  {today}")
    lines.append(
        f"Видео: <b>{total}</b>  ·  500x+: <b>{ultra}</b>  ·  рекорд: <b>{best:.0f}x</b>"
    )
    if min_views > 0:
        lines.append(f"В дайджесте: {_fmt(min_views)}+ просмотров  ·  {len(filtered)} видео")

    # ── Топ-3 ─────────────────────────────────────────────────────────────────
    lines.append("")
    lines.append("─────────────────────────────")
    lines.append("<b>Топ-3 — копировать сегодня</b>")
    lines.append("─────────────────────────────")

    for i, v in enumerate(filtered[:3], 1):
        lines.extend(_fmt_video(i, v))

    # ── Топ 4–10 (тот же формат, без сокращений) ──────────────────────────────
    rest = filtered[3:10]
    if rest:
        lines.append("")
        lines.append("─────────────────────────────")
        lines.append("<b>Топ 4–10</b>")
        lines.append("─────────────────────────────")

        for i, v in enumerate(rest, 4):
            lines.extend(_fmt_video(i, v))

    # ── Футер ─────────────────────────────────────────────────────────────────
    lines.append("")
    lines.append("─────────────────────────────")
    lines.append(
        f'<a href="{report_url}">Полный отчёт с анализом →</a>'
        f"  ·  следующий скан в 9:00"
    )

    _send(token, chat_id, "\n".join(lines))
    logger.info(f"Дайджест отправлен ({len(filtered[:10])} видео, ссылка: {report_url})")


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
    dashboard_url = _get_dashboard_url(cfg)

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
        lines.append(f"<b>{score:.0f}x</b>  ·  @{author}  ·  {source}")
        lines.append(
            f"{views} просм  ·  {subs} подп  ·  "
            f'<a href="{url}">смотреть →</a>'
        )
        lines.append("")

    lines.append(f'<a href="{dashboard_url}">Дашборд →</a>')

    _send(token, chat_id, "\n".join(lines))
    logger.info(f"Алерт: {len(hits)} находок Score≥{ALERT_THRESHOLD}x")
