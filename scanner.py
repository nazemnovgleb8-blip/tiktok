"""
scanner.py — TikTok scraper
Источники: хэштеги, поиск по словам, подписки seed-аккаунтов
Фильтры: Score, дата публикации (7 дней), дедупликация между сканами
"""
import asyncio
import os
import random
import logging
import time
from datetime import datetime, timedelta
from urllib.parse import quote_plus
from playwright.async_api import async_playwright

logger = logging.getLogger("scanner")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins',   { get: () => [1,2,3,4,5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en','ru'] });
Object.defineProperty(navigator, 'platform',  { get: () => 'MacIntel' });
window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {} };
const orig = window.navigator.permissions.query;
window.navigator.permissions.query = (p) =>
    p.name === 'notifications'
    ? Promise.resolve({ state: Notification.permission })
    : orig(p);
"""

# Все известные API эндпоинты TikTok — меняются регулярно
API_PATTERNS = [
    "item_list", "challenge/item", "search/item",
    "music/item", "feed/recommend",
    "api/search/general", "api/search/item", "api/search/video",
    "api/recommend/item_list", "api/post/item_list",
    "aweme/v1/feed", "aweme/v2/feed",
    "general/search", "search/general", "search/full",
    "ttwid", "aweme/detail",  # иногда детали видео приходят так
]


def _parse_item(item: dict, source: str) -> dict | None:
    """Разбирает один элемент TikTok API → dict с полями видео."""
    try:
        stats     = item.get("stats", {}) or item.get("statistics", {})
        play      = (stats.get("playCount") or stats.get("play_count")
                     or item.get("playCount", 0))
        auth_stats = item.get("authorStats", {}) or item.get("author_stats", {})
        followers  = (auth_stats.get("followerCount")
                      or auth_stats.get("follower_count")
                      or item.get("followerCount", 1) or 1)
        author_obj = item.get("author", {})
        author     = (author_obj.get("uniqueId") or author_obj.get("unique_id")
                      or item.get("uniqueId", ""))
        vid_id     = str(item.get("id") or item.get("aweme_id") or "")
        create_ts  = int(item.get("createTime") or item.get("create_time") or 0)

        if not (play and author and vid_id):
            return None

        return {
            "url":              f"https://www.tiktok.com/@{author}/video/{vid_id}",
            "author":           author,
            "source":           source,
            "views":            int(play),
            "followers":        int(followers),
            "score":            round(int(play) / int(followers), 2),
            "video_created_at": create_ts,
        }
    except Exception:
        return None


def _extract_items_from_response(data: dict) -> list:
    """Извлекает список видео из разных форматов TikTok API."""
    # Формат 1: прямые списки
    direct = (data.get("itemList")
              or data.get("item_list")
              or data.get("aweme_list"))
    if direct:
        return direct

    # Формат 2: вложенные в data{}
    d = data.get("data", {})
    if isinstance(d, dict):
        nested = (d.get("itemList") or d.get("item_list")
                  or d.get("aweme_list") or d.get("videos"))
        if nested:
            return nested

    # Формат 3: поиск — data — список блоков с item / aweme_info внутри
    if isinstance(d, list):
        items = []
        for block in d:
            item = (block.get("item")
                    or block.get("aweme_info")
                    or block.get("video"))
            if item:
                items.append(item)
        if items:
            return items

    # Формат 4: data.data[] — двойная вложенность (встречается в новом поиске)
    dd = d.get("data", []) if isinstance(d, dict) else []
    if isinstance(dd, list):
        items = []
        for block in dd:
            item = block.get("item") or block.get("aweme_info")
            if item:
                items.append(item)
        if items:
            return items

    return []


async def _close_popups(page):
    """Закрывает попапы логина, куки, возрастные ограничения."""
    selectors = [
        '[data-e2e="modal-close-inner-button"]',
        '[aria-label="Close"]',
        'button[class*="close"]',
        'div[class*="DismissBar"]',
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass


async def _wait_for_captcha(page, cfg: dict = None) -> bool:
    """Возвращает True если капча решена (или её не было), False — если нет."""
    from captcha import handle_captcha
    return await handle_captcha(page, cfg or {})


async def _click_videos_tab(page):
    """Нажимает вкладку 'Видео' на странице поиска TikTok."""
    selectors = [
        '[data-e2e="search-video-tab"]',
        'a[href*="type=video"]',
        'div[class*="TabBar"] a:has-text("Videos")',
        'div[class*="TabBar"] a:has-text("Видео")',
        'button:has-text("Videos")',
        'button:has-text("Видео")',
        'span:has-text("Videos")',
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=1500):
                await el.click()
                await asyncio.sleep(1.5)
                logger.debug("Нажата вкладка Videos")
                return True
        except Exception:
            pass
    return False


async def _scroll_and_collect(page, url: str, source: str,
                               target: int = 100, max_stale: int = 5,
                               cfg: dict = None,
                               is_search: bool = False) -> list:
    """
    Открывает URL, скроллит пока не наберёт target видео.
    is_search=True — дополнительно кликает по вкладке Videos.
    """
    captured = []
    seen_urls = set()

    async def on_response(response):
        u = response.url
        # Проверяем URL паттерны
        if not any(k in u for k in API_PATTERNS):
            return
        # Игнорируем не-JSON (картинки, css и т.д.)
        ct = response.headers.get("content-type", "")
        if "json" not in ct and "javascript" not in ct:
            return
        try:
            data = await response.json()
            items = _extract_items_from_response(data)
            for item in items:
                parsed = _parse_item(item, source)
                if parsed and parsed["url"] not in seen_urls:
                    seen_urls.add(parsed["url"])
                    captured.append(parsed)
        except Exception:
            pass

    page.on("response", on_response)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=35000)
        await asyncio.sleep(random.uniform(2.0, 3.5))
        captcha_ok = await _wait_for_captcha(page, cfg)
        if not captcha_ok:
            # Капча не решена (headless режим или ddddocr не справился) — пропускаем источник
            logger.warning(f"Капча не решена — пропускаю источник: {source}")
            return []
        await _close_popups(page)

        if is_search:
            # Ждём загрузки поиска и кликаем Videos
            await asyncio.sleep(1.5)
            await _click_videos_tab(page)
            await asyncio.sleep(2.0)

        stale = 0
        for _ in range(60):  # увеличили с 30 до 60 итераций
            prev = len(captured)
            # Более агрессивный скролл — TikTok грузит следующую пачку только при большом сдвиге
            for _ in range(random.randint(3, 5)):
                await page.mouse.wheel(0, random.randint(800, 1400))
                await asyncio.sleep(random.uniform(0.5, 1.0))
            await asyncio.sleep(random.uniform(3.0, 5.0))

            if len(captured) >= target:
                break
            if len(captured) == prev:
                stale += 1
                if stale == 3:
                    # Пробуем резкий скролл вниз — иногда помогает разбудить TikTok
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(3.0)
                if stale >= 8:  # увеличили с 5 до 8
                    break
            else:
                stale = 0

    except Exception as e:
        logger.warning(f"Ошибка при загрузке {url}: {e}")
    finally:
        page.remove_listener("response", on_response)

    return captured


async def _get_following(page, username: str) -> list[str]:
    """Возвращает список аккаунтов на которые подписан username."""
    found = []

    async def on_response(response):
        if "following" in response.url and "list" in response.url:
            try:
                data = await response.json()
                users = (data.get("userList")
                         or data.get("user_list")
                         or data.get("data", {}).get("userList")
                         or [])
                for u in users:
                    uid = (u.get("user", {}) or u).get("uniqueId", "")
                    if uid and uid not in found:
                        found.append(uid)
            except Exception:
                pass

    page.on("response", on_response)
    try:
        await page.goto(f"https://www.tiktok.com/@{username}/following",
                        wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)
        await page.mouse.wheel(0, 3000)
        await asyncio.sleep(1.5)
    except Exception:
        pass
    page.remove_listener("response", on_response)
    return found[:25]


def _is_headless() -> bool:
    """На Railway всегда headless, локально — показываем браузер."""
    return bool(os.environ.get("RAILWAY_ENVIRONMENT") or
                os.environ.get("HEADLESS", ""))


async def _build_context(p, cfg: dict) -> tuple:
    session_file = cfg["session_file"]
    chrome_path  = cfg.get("chrome_path", "")
    profile_dir  = os.path.expanduser(cfg.get("profile_dir", ""))

    headless = _is_headless()
    proxy    = cfg.get("proxy", "").strip().rstrip("/")
    launch_args = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
    ]
    if headless:
        launch_args += ["--disable-gpu", "--single-process"]

    proxy_cfg = {"server": proxy} if proxy else None
    if proxy:
        logger.info(f"Прокси: {proxy.split('@')[-1]}")  # не логируем пароль

    ctx_kwargs = dict(
        user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"),
        viewport={"width": 1280, "height": 800},
        locale="ru-RU",
    )
    if proxy_cfg:
        ctx_kwargs["proxy"] = proxy_cfg

    if os.path.exists(session_file):
        logger.info(f"Загружаю сохранённую сессию (headless={headless})...")
        browser = await p.chromium.launch(
            headless=headless,
            args=launch_args,
            proxy=proxy_cfg,
        )
        context = await browser.new_context(
            storage_state=session_file,
            **ctx_kwargs,
        )
        return context, browser

    if headless:
        # На сервере без сессии — просто запускаем без профиля
        logger.warning("Нет сессии — запускаю без авторизации (headless)")
        browser = await p.chromium.launch(headless=True, args=launch_args)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ru-RU",
        )
        return context, browser

    # Локально — используем Chrome профиль
    logger.info("Сессии нет — запускаю Chrome профиль...")
    if profile_dir and not os.path.exists(profile_dir):
        import shutil
        src = os.path.expanduser(
            "~/Library/Application Support/Google/Chrome/Default"
        )
        if os.path.exists(src):
            logger.info(f"Копирую профиль {src} → {profile_dir}")
            shutil.copytree(src, profile_dir)

    if profile_dir and os.path.exists(profile_dir) and chrome_path and os.path.exists(chrome_path):
        persistent_kwargs = dict(
            user_data_dir=profile_dir,
            executable_path=chrome_path,
            headless=False,
            slow_mo=100,
            args=launch_args,
            viewport={"width": 1280, "height": 800},
            locale="ru-RU",
        )
        if proxy_cfg:
            persistent_kwargs["proxy"] = proxy_cfg
        context = await p.chromium.launch_persistent_context(**persistent_kwargs)
        return context, None

    # Fallback — Playwright Chromium без профиля
    browser = await p.chromium.launch(headless=False, args=launch_args)
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800}, locale="ru-RU"
    )
    return context, browser


async def run_scan(cfg: dict,
                   on_progress=None,
                   need_login: bool = False) -> tuple[list, list]:
    """
    Главная функция сканирования.
    Возвращает (все_видео, отфильтрованные).

    Фильтры:
      - Score >= min_score
      - Опубликовано не позже max_age_days дней назад
      - Не было сохранено в БД за последние dedup_days дней
    """

    def log(msg):
        logger.info(msg)
        if on_progress:
            on_progress(msg)

    # ── Загружаем уже известные URL из БД (дедупликация) ──────────────────────
    import database as db_mod
    known_urls = db_mod.get_known_urls(days=30)
    log(f"📋 Известных URL в БД (30 дн): {len(known_urls)} — пропускаем повторы")

    # ── Порог по дате ─────────────────────────────────────────────────────────
    max_age_days = cfg.get("max_age_days", 7)
    week_ago_ts  = int((datetime.now() - timedelta(days=max_age_days)).timestamp())
    log(f"📅 Фильтр по дате: не старше {max_age_days} дней")

    all_videos: list[dict] = []
    seen_urls: set[str]    = set()

    def add(videos: list[dict]):
        """Добавляет видео в буфер, пропуская дубли и уже известные URL."""
        new_count = 0
        dup_count = 0
        for v in videos:
            u = v["url"]
            if u in seen_urls or u in known_urls:
                dup_count += 1
                continue
            seen_urls.add(u)
            all_videos.append(v)
            new_count += 1
        if dup_count:
            logger.debug(f"  Пропущено дублей: {dup_count}")
        return new_count

    target = cfg.get("target_per_source", 30)

    # Если подряд ZERO_LIMIT источников вернули 0 видео — скорее всего капча/нет сессии
    ZERO_LIMIT    = 5
    zero_streak   = 0
    blocked       = False

    def track_zeros(count: int) -> bool:
        """Возвращает True если надо остановить скан (слишком много нулей подряд)."""
        nonlocal zero_streak, blocked
        if count == 0:
            zero_streak += 1
        else:
            zero_streak = 0
        if zero_streak >= ZERO_LIMIT:
            blocked = True
            return True
        return False

    async with async_playwright() as p:
        context, browser = await _build_context(p, cfg)
        page = await context.new_page()
        await page.add_init_script(STEALTH_JS)

        # ── Проверка логина ────────────────────────────────────────────────────
        home_loaded = False
        try:
            await page.goto("https://www.tiktok.com", wait_until="domcontentloaded",
                            timeout=60000)
            home_loaded = True
        except Exception as e:
            log(f"⚠️  TikTok главная не загрузилась ({type(e).__name__}) — проверяю сессию по cookies...")

        await asyncio.sleep(2)

        # Проверяем логин: по cookies (работает даже без загрузки страницы) или по DOM
        try:
            is_logged = await page.evaluate(
                "() => document.cookie.includes('sessionid') || "
                "!!document.querySelector('[data-e2e=\"profile-icon\"]')"
            )
        except Exception:
            is_logged = False

        if not is_logged:
            if _is_headless():
                if not home_loaded:
                    # Страница не загрузилась — сессия неизвестна, пробуем сканировать
                    log("⚠️  Не удалось проверить сессию (таймаут) — пробую сканировать...")
                else:
                    # Страница загрузилась, но не залогинен
                    log("⛔ Сессия устарела — скан отменён. Загрузи tiktok_session.json через Настройки.")
                    if browser:
                        await browser.close()
                    else:
                        await context.close()
                    return [], []
            else:
                log("⚠️  Сессия устарела — залогинься в браузере и нажми Enter.")
                input("    → Enter после логина... ")
                await asyncio.sleep(2)
        elif need_login and not _is_headless():
            log("ℹ️  Принудительная переавторизация — залогинься и нажми Enter.")
            input("    → Enter после логина... ")
            await asyncio.sleep(2)
        else:
            log("✓ Авторизация подтверждена")

        await context.storage_state(path=cfg["session_file"])
        log("✓ Сессия сохранена")

        # ── 1. Хэштеги ────────────────────────────────────────────────────────
        log(f"\n[1/3] Хэштеги ({len(cfg['hashtags'])} штук)...")
        for tag in cfg["hashtags"]:
            log(f"  #{tag}...")
            videos = await _scroll_and_collect(
                page, f"https://www.tiktok.com/tag/{tag}",
                source=f"#{tag}", target=target, cfg=cfg
            )
            new = add(videos)
            log(f"  #{tag} → {len(videos)} получено, {new} новых (всего: {len(all_videos)})")
            if track_zeros(len(videos)):
                log("⛔ 5 источников подряд вернули 0 — похоже капча или нет сессии. Останавливаю скан.")
                break
            await asyncio.sleep(random.uniform(8, 15))

        # ── 2. Поиск ──────────────────────────────────────────────────────────
        if not blocked:
            log(f"\n[2/3] Поиск ({len(cfg['search_queries'])} запросов)...")
            for query in cfg["search_queries"]:
                log(f"  \"{query}\"...")
                search_url = (
                    f"https://www.tiktok.com/search/video?q={quote_plus(query)}"
                )
                videos = await _scroll_and_collect(
                    page, search_url,
                    source=f"search:{query}", target=target, cfg=cfg,
                    is_search=True
                )
                # Если нашли мало — пробуем второй формат
                if len(videos) < 3:
                    log(f"  Мало результатов, пробую альтернативный URL...")
                    alt_url = (
                        f"https://www.tiktok.com/search?q={quote_plus(query)}&type=video"
                    )
                    videos2 = await _scroll_and_collect(
                        page, alt_url,
                        source=f"search:{query}", target=target, cfg=cfg,
                        is_search=True
                    )
                    videos = videos or videos2
                    if videos2:
                        videos = videos + [v for v in videos2 if v["url"] not in {x["url"] for x in videos}]

                new = add(videos)
                log(f"  \"{query}\" → {len(videos)} получено, {new} новых (всего: {len(all_videos)})")
                if track_zeros(len(videos)):
                    log("⛔ 5 источников подряд вернули 0 — похоже капча или нет сессии. Останавливаю скан.")
                    break
                await asyncio.sleep(random.uniform(10, 18))

        # ── 3. Подписки seed-аккаунтов ────────────────────────────────────────
        if blocked:
            log("⛔ Скан остановлен досрочно — загрузи актуальную сессию TikTok через Настройки дашборда")
        log(f"\n[3/3] Аккаунты из ниши..." if not blocked else "")
        discovered: list[str] = []

        for acc in ([] if blocked else cfg["seed_accounts"]):
            log(f"  @{acc} → подписки...")
            following = await _get_following(page, acc)
            discovered.extend(following)
            log(f"  @{acc} → {len(following)} подписок")
            await asyncio.sleep(random.uniform(5, 10))

        unique_accounts = list(dict.fromkeys(
            a for a in discovered if a not in cfg["seed_accounts"]
        ))[:10]

        log(f"  Уникальных аккаунтов: {len(unique_accounts)}")

        for acc in ([] if blocked else cfg["seed_accounts"] + unique_accounts):
            log(f"  @{acc}...")
            videos = await _scroll_and_collect(
                page, f"https://www.tiktok.com/@{acc}",
                source=f"account:{acc}", target=20, cfg=cfg
            )
            new = add(videos)
            log(f"  @{acc} → {len(videos)} получено, {new} новых (всего: {len(all_videos)})")
            await asyncio.sleep(random.uniform(8, 15))

        if browser:
            await browser.close()
        else:
            await context.close()

    # ── Финальная фильтрация ───────────────────────────────────────────────────
    min_score = cfg.get("min_score", 10)

    # Фильтр по дате: оставляем только видео <= max_age_days дней
    # (video_created_at == 0 — дата неизвестна, пропускаем этот фильтр)
    date_filtered = [
        v for v in all_videos
        if v.get("video_created_at", 0) == 0
        or v["video_created_at"] >= week_ago_ts
    ]
    date_dropped = len(all_videos) - len(date_filtered)
    if date_dropped:
        log(f"📅 Отфильтровано по дате (>{max_age_days} дн): {date_dropped} видео")

    result = [v for v in date_filtered if v["score"] >= min_score]
    result.sort(key=lambda x: x["score"], reverse=True)

    log(f"\n✅ Сканирование завершено.")
    log(f"   Всего уникальных новых: {len(all_videos)}")
    log(f"   После фильтра по дате: {len(date_filtered)}")
    log(f"   С Score≥{min_score}: {len(result)}")

    return all_videos, result
