"""
captcha.py — автоматическое решение капчи TikTok через CapSolver
https://capsolver.com — регистрация бесплатная, ~$1-2/мес при нашем объёме

Если api_key не задан — падает обратно на ручное решение.
"""
import asyncio
import logging
import random
import time

logger = logging.getLogger("captcha")

CAPTCHA_SELECTORS = [
    '[id*="captcha"]',
    '[class*="captcha"]',
    '[class*="secsdk"]',
    '[class*="cap-flex"]',
    'iframe[src*="captcha"]',
    '[class*="verify"]',
    '#captcha-verify-image',
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


async def solve_with_ddddocr(page) -> bool:
    """
    Бесплатное решение slider-капчи TikTok через ddddocr.
    pip install ddddocr --break-system-packages
    """
    try:
        import ddddocr
        import base64

        # Ищем элементы слайдера
        bg_sel    = 'img[src*="captcha"][class*="bg"], img[id*="captcha-verify-image"], canvas'
        piece_sel = 'img[src*="captcha"][class*="piece"], img[class*="cap-piece"]'

        bg_el    = page.locator(bg_sel).first
        piece_el = page.locator(piece_sel).first

        if not await bg_el.is_visible(timeout=2000):
            return False

        # Скриншоты фона и кусочка
        bg_bytes    = await bg_el.screenshot()
        piece_bytes = await piece_el.screenshot() if await piece_el.is_visible(timeout=1000) else None

        if not piece_bytes:
            return False

        slide = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)
        result = slide.slide_match(piece_bytes, bg_bytes, simple_target=True)
        target_x = result["target"][0]

        # Находим слайдер-кнопку
        slider_sel = '[class*="secsdk-captcha-drag-icon"], [class*="captcha_verify_slide"], [class*="slider"]'
        slider = page.locator(slider_sel).first

        if not await slider.is_visible(timeout=2000):
            return False

        box = await slider.bounding_box()
        if not box:
            return False

        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2

        # Человекоподобное перетаскивание
        await page.mouse.move(start_x, start_y)
        await page.mouse.down()
        await asyncio.sleep(0.3)

        steps = 20
        for i in range(steps):
            progress = i / steps
            # Лёгкое ускорение в начале, замедление в конце
            eased = progress * progress * (3 - 2 * progress)
            curr_x = start_x + target_x * eased
            jitter = random.uniform(-1.5, 1.5)
            await page.mouse.move(curr_x + jitter, start_y + jitter)
            await asyncio.sleep(random.uniform(0.01, 0.04))

        await page.mouse.move(start_x + target_x, start_y)
        await asyncio.sleep(0.2)
        await page.mouse.up()
        await asyncio.sleep(1.5)

        # Проверяем исчезла ли капча
        if not await is_captcha_visible(page):
            logger.info("✅ Slider-капча решена через ddddocr (бесплатно)")
            return True

    except ImportError:
        logger.info("ddddocr не установлен — пропускаю")
    except Exception as e:
        logger.warning(f"ddddocr не смог решить: {e}")

    return False


async def solve_with_capsolver(page, api_key: str) -> bool:
    """
    Пытается решить TikTok капчу через CapSolver API.
    Возвращает True если успешно.
    """
    try:
        import capsolver
        capsolver.api_key = api_key

        url = page.url
        logger.info(f"Отправляю капчу в CapSolver для {url}...")

        # CapSolver поддерживает TikTok Captcha нативно
        solution = capsolver.solve({
            "type": "TikTokCaptchaTask",
            "websiteURL": url,
        })

        if solution and solution.get("token"):
            # Применяем токен через JS
            token = solution["token"]
            await page.evaluate(f"""
                () => {{
                    if (window.byted_acrawler) {{
                        window.byted_acrawler.frontierSign('{token}');
                    }}
                    // Пробуем через fetch callback
                    const callbacks = window.__captcha_callbacks || [];
                    callbacks.forEach(cb => {{ try {{ cb('{token}'); }} catch(e) {{}} }});
                }}
            """)
            await asyncio.sleep(2)
            logger.info("✅ Капча решена через CapSolver")
            return True

    except ImportError:
        logger.warning("capsolver не установлен: pip install capsolver --break-system-packages")
    except Exception as e:
        logger.warning(f"CapSolver не смог решить: {e}")

    return False


async def solve_with_2captcha(page, api_key: str) -> bool:
    """
    Резервный вариант — решение через 2captcha (image CAPTCHA).
    Делает скриншот, отправляет оператору, получает координаты.
    """
    try:
        import requests as req

        # Скриншот области капчи
        screenshot = await page.screenshot(full_page=False)

        logger.info("Отправляю скриншот в 2captcha...")
        import base64
        b64 = base64.b64encode(screenshot).decode()

        # Загружаем задачу
        r = req.post("https://2captcha.com/in.php", data={
            "key": api_key,
            "method": "base64",
            "body": b64,
            "coordinatescaptcha": 1,
            "json": 1,
        }, timeout=15)
        result = r.json()
        if result.get("status") != 1:
            logger.warning(f"2captcha отклонил: {result}")
            return False

        task_id = result["request"]
        logger.info(f"2captcha task_id={task_id}, жду решения...")

        # Ждём ответа (до 90 секунд)
        for _ in range(18):
            await asyncio.sleep(5)
            r2 = req.get(f"https://2captcha.com/res.php?key={api_key}&action=get&id={task_id}&json=1", timeout=10)
            res = r2.json()
            if res.get("status") == 1:
                logger.info(f"✅ 2captcha решила: {res['request']}")
                return True
            if res.get("request") not in ("CAPCHA_NOT_READY", "CAPTCHA_NOT_READY"):
                logger.warning(f"2captcha ошибка: {res}")
                return False

    except Exception as e:
        logger.warning(f"2captcha ошибка: {e}")

    return False


async def handle_captcha(page, cfg: dict) -> None:
    """
    Главная функция: проверяет капчу и пытается решить автоматически.
    Если не получается — просит пользователя решить вручную.
    """
    if not await is_captcha_visible(page):
        return

    logger.warning("⚠️  Обнаружена капча TikTok!")

    # 1. Пробуем бесплатный ddddocr (slider-капча)
    if await solve_with_ddddocr(page):
        return

    # 2. Пробуем CapSolver
    capsolver_key = cfg.get("capsolver_api_key", "")
    if capsolver_key:
        success = await solve_with_capsolver(page, capsolver_key)
        if success:
            return

    # Пробуем 2captcha
    captcha2_key = cfg.get("2captcha_api_key", "")
    if captcha2_key:
        success = await solve_with_2captcha(page, captcha2_key)
        if success:
            return

    # Ручное решение
    logger.warning("Авто-решение недоступно — решай капчу вручную")
    print("\n" + "━" * 50)
    print("  ⚠️  TikTok показал КАПЧУ!")
    print("  Реши её в окне браузера и нажми Enter.")
    print("  (Чтобы автоматизировать — добавь capsolver_api_key в настройки)")
    print("━" * 50)
    input("  → Enter после решения: ")
    await asyncio.sleep(2)
