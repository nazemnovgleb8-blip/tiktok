"""
captcha.py — автоматическое решение капчи TikTok
Порядок попыток:
  1. ddddocr (бесплатно, slider-капча)
  2. CapSolver API (платно, если задан capsolver_api_key)
  3. Ручное решение (только в интерактивном режиме)
"""
import asyncio
import logging
import random
import os

logger = logging.getLogger("captcha")

# ── Селекторы для определения наличия капчи ───────────────────────────────────
CAPTCHA_SELECTORS = [
    '[id*="captcha"]',
    '[class*="captcha"]',
    '[class*="secsdk"]',
    '[class*="cap-flex"]',
    'iframe[src*="captcha"]',
    '[class*="verify"]',
    '#captcha-verify-image',
    '[class*="captcha_verify"]',
]

# ── Селекторы фонового изображения (bg) для slider-капчи ─────────────────────
BG_SELECTORS = [
    '#captcha-verify-image',
    'img[class*="captcha_verify_img_slide"]',
    'img[class*="verify-image"]',
    'img[class*="bg-img"]',
    'img[id*="captcha"]',
    'canvas[id*="captcha"]',
    '.captcha_verify_img--bg',
    '[class*="captcha-bg"]',
]

# ── Селекторы кусочка пазла ───────────────────────────────────────────────────
PIECE_SELECTORS = [
    'img[class*="captcha_verify_img--move"]',
    'img[class*="cap-piece"]',
    'img[class*="move-img"]',
    'img[class*="puzzle-piece"]',
    '.captcha_verify_img--move',
    '[class*="captcha-piece"]',
]

# ── Селекторы кнопки слайдера ─────────────────────────────────────────────────
SLIDER_SELECTORS = [
    '#captcha-slider-thumb',
    '[class*="secsdk-captcha-drag-icon"]',
    '[class*="captcha_verify_slide--btn"]',
    '[class*="slider_thumb"]',
    '[class*="slide-btn"]',
    '[class*="drag-icon"]',
    'div[class*="slider"][class*="captcha"]',
]


async def is_captcha_visible(page) -> bool:
    """Возвращает True если на странице есть капча."""
    for sel in CAPTCHA_SELECTORS:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=800):
                return True
        except Exception:
            pass
    return False


async def _find_element(page, selectors: list, timeout: int = 2000):
    """Ищет первый видимый элемент из списка селекторов."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=timeout):
                return el, sel
        except Exception:
            pass
    return None, None


async def _human_slide(page, slider_el, distance: int):
    """Человекоподобное перетаскивание слайдера на distance пикселей."""
    box = await slider_el.bounding_box()
    if not box:
        return

    start_x = box["x"] + box["width"] / 2
    start_y = box["y"] + box["height"] / 2

    await page.mouse.move(start_x, start_y)
    await asyncio.sleep(random.uniform(0.1, 0.3))
    await page.mouse.down()
    await asyncio.sleep(random.uniform(0.1, 0.2))

    # Движение с easing + небольшим джиттером
    steps = random.randint(20, 30)
    for i in range(steps):
        t = (i + 1) / steps
        # ease-in-out
        eased = t * t * (3 - 2 * t)
        curr_x = start_x + distance * eased
        jitter_x = random.uniform(-1.0, 1.0)
        jitter_y = random.uniform(-1.5, 1.5)
        await page.mouse.move(curr_x + jitter_x, start_y + jitter_y)
        await asyncio.sleep(random.uniform(0.008, 0.030))

    # Немного назад перед отпусканием (как человек)
    await page.mouse.move(start_x + distance - random.uniform(2, 5), start_y)
    await asyncio.sleep(random.uniform(0.05, 0.1))
    await page.mouse.move(start_x + distance, start_y)
    await asyncio.sleep(random.uniform(0.1, 0.2))
    await page.mouse.up()
    await asyncio.sleep(2.0)


async def solve_with_ddddocr(page) -> bool:
    """
    Бесплатное решение slider-капчи TikTok через ddddocr.
    Устанавливается: pip install ddddocr --break-system-packages
    """
    try:
        import ddddocr

        logger.info("Пробую ddddocr для slider-капчи...")

        # Ищем фон и кусочек пазла
        bg_el, bg_sel = await _find_element(page, BG_SELECTORS, timeout=3000)
        if bg_el is None:
            logger.debug("Фоновое изображение капчи не найдено")
            return False

        piece_el, piece_sel = await _find_element(page, PIECE_SELECTORS, timeout=2000)
        if piece_el is None:
            logger.debug("Кусочек пазла не найден")
            return False

        logger.debug(f"Нашёл bg='{bg_sel}', piece='{piece_sel}'")

        # Скриншоты элементов
        bg_bytes    = await bg_el.screenshot()
        piece_bytes = await piece_el.screenshot()

        if not bg_bytes or not piece_bytes:
            return False

        # ddddocr определяет на сколько пикселей сдвинуть
        slide = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)
        result = slide.slide_match(piece_bytes, bg_bytes, simple_target=True)
        target_x = result["target"][0]
        logger.info(f"ddddocr → сдвиг: {target_x}px")

        if target_x < 5:
            logger.warning("ddddocr вернул слишком маленький сдвиг — пропускаю")
            return False

        # Ищем кнопку слайдера
        slider_el, slider_sel = await _find_element(page, SLIDER_SELECTORS, timeout=2000)
        if slider_el is None:
            # Пробуем взять контейнер пазла как слайдер
            logger.debug("Кнопка слайдера не найдена стандартными селекторами")
            return False

        # Тянем
        await _human_slide(page, slider_el, target_x)

        # Проверяем результат
        await asyncio.sleep(1.0)
        if not await is_captcha_visible(page):
            logger.info("✅ Slider-капча решена через ddddocr!")
            return True

        # Иногда нужно несколько попыток с корректировкой
        logger.debug("Первая попытка не прошла — пробую ещё раз с корректировкой")
        for attempt in range(2):
            if not await is_captcha_visible(page):
                break
            # Небольшая коррекция ±10%
            adj = target_x * random.uniform(0.88, 1.12)
            await _human_slide(page, slider_el, int(adj))
            await asyncio.sleep(1.5)

        if not await is_captcha_visible(page):
            logger.info(f"✅ Slider-капча решена через ddddocr (со второй попытки)!")
            return True

    except ImportError:
        logger.info("ddddocr не установлен — pip install ddddocr --break-system-packages")
    except Exception as e:
        logger.warning(f"ddddocr ошибка: {e}")

    return False


async def solve_with_capsolver(page, api_key: str) -> bool:
    """
    Решение через CapSolver API (~$1-2/мес при нашем объёме).
    pip install capsolver --break-system-packages
    """
    try:
        import capsolver
        capsolver.api_key = api_key

        url = page.url
        logger.info(f"Отправляю капчу в CapSolver для {url}...")

        solution = capsolver.solve({
            "type": "TikTokCaptchaTask",
            "websiteURL": url,
        })

        if solution and solution.get("token"):
            token = solution["token"]
            await page.evaluate(f"""
                () => {{
                    if (window.byted_acrawler) {{
                        window.byted_acrawler.frontierSign('{token}');
                    }}
                    const callbacks = window.__captcha_callbacks || [];
                    callbacks.forEach(cb => {{ try {{ cb('{token}'); }} catch(e) {{}} }});
                }}
            """)
            await asyncio.sleep(2)
            if not await is_captcha_visible(page):
                logger.info("✅ Капча решена через CapSolver!")
                return True

    except ImportError:
        logger.warning("capsolver не установлен: pip install capsolver --break-system-packages")
    except Exception as e:
        logger.warning(f"CapSolver ошибка: {e}")

    return False


async def handle_captcha(page, cfg: dict) -> bool:
    """
    Главная функция: проверяет капчу и пытается решить автоматически.
    Возвращает True если капча решена (или её не было), False — если не смогли.
    В headless/Railway режиме НЕ блокирует на ручном вводе.
    """
    if not await is_captcha_visible(page):
        return True

    logger.warning("⚠️  Обнаружена капча TikTok!")

    # 1. ddddocr (бесплатно, slider)
    if await solve_with_ddddocr(page):
        return True

    # 2. CapSolver (платно, если задан ключ)
    capsolver_key = cfg.get("capsolver_api_key", "")
    if capsolver_key:
        if await solve_with_capsolver(page, capsolver_key):
            return True

    # 3. Ручное решение — только в интерактивном (не headless) режиме
    is_headless = bool(os.environ.get("RAILWAY_ENVIRONMENT")) or cfg.get("headless", False)
    if is_headless:
        logger.warning("Headless режим — пропускаю источник с капчей (не могу решить вручную)")
        return False

    logger.warning("Авто-решение недоступно — решай капчу вручную в браузере")
    print("\n" + "━" * 55)
    print("  ⚠️   TikTok показал КАПЧУ!")
    print("  Реши её в окне браузера, затем нажми Enter.")
    print("  (Для автоматизации: добавь capsolver_api_key в настройки)")
    print("━" * 55)
    try:
        input("  → Enter после решения: ")
    except EOFError:
        # Если stdin закрыт (запуск в фоне) — пропускаем
        return False
    await asyncio.sleep(2)
    return not await is_captcha_visible(page)
