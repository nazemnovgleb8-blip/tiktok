"""
analyzer.py — Gemini Vision анализ видео
Скриншот первого кадра + описание → категория, релевантность, хук, адаптация
"""
import asyncio
import base64
import logging
import os
import re
import tempfile
import time

logger = logging.getLogger("analyzer")

ALTA_CONTEXT = """
Alta — агентство упаковки бизнеса (сайты, брендинг, AI-контент).
Клиенты: малый и средний бизнес, которому нужно выглядеть на уровень выше.
Наши направления:
1. Брендинг / айдентика — логотипы, фирменный стиль, ребрендинг
2. Сайты / веб-дизайн — лендинги, корпоративные сайты, интернет-магазины
3. ИИ-контент — AI-видео, автоматизация контента, нейросети в работе
4. Просто вирал — форматы которые дают охват и приводят аудиторию в воронку
"""

GEMINI_PROMPT = """Ты — эксперт по контент-маркетингу агентства Alta.

Контекст агентства:
{context}

Проанализируй это TikTok-видео (скриншот + мета-данные) и ответь строго в формате JSON:

{{
  "category": "брендинг" | "сайты" | "ии-контент" | "вирал",
  "relevance": <число 1-10>,
  "hook": "<опиши хук первых 2-3 секунд одной фразой>",
  "why_viral": "<почему залетело — одно предложение>",
  "adaptation": "<конкретная идея как Alta может адаптировать этот формат>",
  "priority": "высокий" | "средний" | "низкий"
}}

Метаданные видео:
- Источник (хэштег/поиск): {source}
- Автор: @{author}
- Просмотры: {views}
- Подписчиков: {followers}
- Score (просмотры/подписчики): {score}x

Оценивай строго — relevance 8+ только если Alta реально может сделать похожее и получить клиентов.
Отвечай только JSON без лишнего текста."""


async def _screenshot_tiktok(url: str, browser) -> bytes | None:
    """Открывает TikTok видео и делает скриншот. Таймаут 15 сек — не блокирует."""
    try:
        page = await browser.new_page(viewport={"width": 800, "height": 600})
        await page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "window.chrome={runtime:{}};"
        )
        # Жёсткий таймаут — если не загрузилось за 12 сек, идём дальше
        try:
            await asyncio.wait_for(
                page.goto(url, wait_until="domcontentloaded", timeout=12000),
                timeout=12
            )
        except Exception:
            pass  # Делаем скриншот того что есть
        await asyncio.sleep(1.5)

        # Закрываем попапы
        for sel in ['[data-e2e="modal-close-inner-button"]', '[aria-label="Close"]']:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=500):
                    await btn.click()
            except Exception:
                pass

        screenshot = await page.screenshot(full_page=False)
        await page.close()
        return screenshot
    except Exception as e:
        logger.warning(f"Скриншот не удался для {url}: {e}")
        try:
            await page.close()
        except Exception:
            pass
        return None


def _call_gemini(api_key: str, screenshot: bytes | None, video: dict) -> dict:
    """Отправляет данные в Gemini и получает анализ."""
    # Порядок моделей: пробуем по очереди если квота исчерпана
    MODELS = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-1.5-flash"]

    try:
        import google.genai as genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        model_name = MODELS[0]  # начинаем с первой
    except ImportError:
        import google.generativeai as genai_old
        import warnings
        warnings.filterwarnings("ignore")
        genai_old.configure(api_key=api_key)
        model = genai_old.GenerativeModel("gemini-1.5-flash")
        client = None
        model_name = "gemini-1.5-flash"

    prompt = GEMINI_PROMPT.format(
        context=ALTA_CONTEXT,
        source=video.get("source", ""),
        author=video.get("author", ""),
        views=f"{video.get('views', 0):,}",
        followers=f"{video.get('followers', 0):,}",
        score=video.get("score", 0),
    )

    import json as _json

    parts_data = [prompt]
    if screenshot and client:
        parts_data.append(types.Part.from_bytes(data=screenshot, mime_type="image/png"))
    elif screenshot:
        parts_data.append({"mime_type": "image/png",
                            "data": base64.b64encode(screenshot).decode()})

    # Пробуем модели по очереди, с retry при 429
    models_to_try = MODELS if client else ["gemini-1.5-flash"]
    for attempt_model in models_to_try:
        for attempt in range(3):  # 3 попытки на каждую модель
            try:
                if client:
                    response = client.models.generate_content(
                        model=attempt_model, contents=parts_data)
                    text = response.text.strip()
                else:
                    response = model.generate_content(parts_data)
                    text = response.text.strip()

                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
                return _json.loads(text)

            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    if "retry" in err.lower():
                        # Извлекаем время ожидания из ошибки
                        import re as _re
                        match = _re.search(r"retry.*?(\d+)s", err, _re.IGNORECASE)
                        wait = int(match.group(1)) + 2 if match else 30
                    else:
                        wait = 30
                    logger.warning(f"Квота {attempt_model} исчерпана, жду {wait}с...")
                    time.sleep(wait)
                else:
                    logger.warning(f"Ошибка Gemini ({attempt_model}): {e}")
                    break  # Не 429 — переходим к следующей модели

    logger.warning("Все модели Gemini недоступны — пропускаю видео")
    return {
        "category": "вирал", "relevance": 5,
        "hook": "", "why_viral": "", "adaptation": "", "priority": "средний"
    }


async def analyze_videos(videos: list[dict], cfg: dict) -> list[dict]:
    """
    Берёт топ N видео по Score, делает скриншоты, отправляет в Gemini.
    Возвращает те же видео но с полями: category, relevance, hook, why_viral,
    adaptation, priority, gemini_done=True
    """
    api_key = cfg.get("gemini_api_key", "")
    if not api_key:
        logger.warning("Gemini API key не задан — пропускаю AI-анализ")
        for v in videos:
            v.update({"category": "вирал", "relevance": 0, "hook": "",
                       "why_viral": "", "adaptation": "", "priority": "средний",
                       "gemini_done": False})
        return videos

    top_n = cfg.get("gemini_top_n", 50)
    top_videos = videos[:top_n]
    rest       = videos[top_n:]

    # Пропускаем уже проанализированные
    to_analyze = [v for v in top_videos if not v.get("gemini_done") and v.get("gemini_relevance", 0) == 0]
    already    = [v for v in top_videos if v.get("gemini_done") or v.get("gemini_relevance", 0) > 0]

    if already:
        logger.info(f"Пропускаю {len(already)} уже проанализированных видео")
    if not to_analyze:
        logger.info("Все видео уже проанализированы — пропускаю Gemini")
        return already + rest

    logger.info(f"Анализирую {len(to_analyze)} видео через Gemini...")

    from playwright.async_api import async_playwright
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for i, video in enumerate(to_analyze):
            logger.info(f"  [{i+1}/{len(to_analyze)}] {video['url']}")

            screenshot = await _screenshot_tiktok(video["url"], browser)
            analysis   = _call_gemini(api_key, screenshot, video)

            video.update({
                "category":   analysis.get("category", "вирал"),
                "relevance":  analysis.get("relevance", 5),
                "hook":       analysis.get("hook", ""),
                "why_viral":  analysis.get("why_viral", ""),
                "adaptation": analysis.get("adaptation", ""),
                "priority":   analysis.get("priority", "средний"),
                "gemini_done": True,
            })
            results.append(video)

            # 10 запросов в минуту = 6 сек между запросами
            eta_min = round((len(to_analyze) - i - 1) * 6 / 60, 1)
            logger.info(f"  ⏱ Пауза 6 сек... (осталось ~{eta_min} мин)")
            await asyncio.sleep(6)

        await browser.close()

    # Добавляем уже проанализированные обратно
    results = already + results

    # Остальным ставим дефолтные значения
    for video in rest:
        video.update({"category": "вирал", "relevance": 0, "hook": "",
                       "why_viral": "", "adaptation": "", "priority": "средний",
                       "gemini_done": False})

    return results + rest
