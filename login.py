"""
login.py — ручная авторизация TikTok
Открывает ТВОЙ Chrome с ТВОИМ профилем (не копию).
Просто зайди в TikTok как обычно — скрипт сохранит сессию и выйдет.

Запуск: python3 login.py
"""
import asyncio
import os
import sys

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tiktok_session.json")
CHROME_PATH  = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE_DIR  = os.path.expanduser("~/Library/Application Support/Google/Chrome/Default")


async def main():
    from playwright.async_api import async_playwright

    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Alta Viral Scout — сохранение TikTok-сессии")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("\nОткрываю Chrome с твоим профилем...")
    print("Войди в TikTok как обычно (если ещё не вошёл).")
    print("Когда увидишь свою ленту — нажми Enter здесь.\n")

    async with async_playwright() as p:
        # Используем ТВОЙ реальный Chrome профиль — никаких копий
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            executable_path=CHROME_PATH,
            headless=False,
            slow_mo=50,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--profile-directory=Default",
            ],
            viewport={"width": 1280, "height": 800},
        )

        page = await context.new_page()
        await page.goto("https://www.tiktok.com", wait_until="domcontentloaded", timeout=30000)

        print("Браузер открылся. Залогинься и нажми Enter в этом окне...")
        input("  → Enter после входа: ")

        # Проверяем что залогинились
        is_logged = await page.evaluate(
            "() => document.cookie.includes('sessionid') || "
            "!!document.querySelector('[data-e2e=\"profile-icon\"]')"
        )

        if is_logged:
            await context.storage_state(path=SESSION_FILE)
            print(f"\n✅ Сессия сохранена в {SESSION_FILE}")
            print("   Теперь запускай: python3 main.py\n")
        else:
            print("\n⚠️  Похоже TikTok не показывает твой профиль.")
            print("   Убедись что ты залогинился и попробуй снова.\n")

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
