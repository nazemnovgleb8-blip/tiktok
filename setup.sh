#!/bin/bash
# Alta Viral Scanner — первоначальная установка
# Запуск: chmod +x setup.sh && ./setup.sh

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Alta Viral Scanner — установка зависимостей"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# pip
pip3 install -r requirements.txt --break-system-packages

# Playwright браузеры
echo ""
echo "Устанавливаю Playwright Chromium..."
playwright install chromium

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Готово! Следующие шаги:"
echo ""
echo "  1. Открой config.json и впиши telegram_chat_id"
echo "     (или сделай это через веб-дашборд на localhost:5000)"
echo ""
echo "  2. Первый запуск (нужна авторизация TikTok):"
echo "     python3 main.py --login"
echo ""
echo "  3. Обычный запуск:"
echo "     python3 main.py"
echo ""
echo "  4. Быстрый тест (скан прямо сейчас):"
echo "     python3 main.py --now"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
