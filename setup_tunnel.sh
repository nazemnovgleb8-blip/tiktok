#!/bin/bash
# setup_tunnel.sh — устанавливает cloudflared и регистрирует LaunchAgent

set -e

echo "╔══════════════════════════════════════╗"
echo "║  Alta Viral Scout — Установка туннеля ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. Устанавливаем cloudflared ─────────────────────────────────────────────
if ! command -v cloudflared &>/dev/null && [ ! -f /opt/homebrew/bin/cloudflared ]; then
    echo "▶ Устанавливаю cloudflared..."
    brew install cloudflared
    echo "✓ cloudflared установлен"
else
    echo "✓ cloudflared уже установлен: $(cloudflared --version 2>/dev/null | head -1)"
fi

echo ""
echo "✅ Готово!"
echo ""
echo "Туннель запускается автоматически вместе с дашбордом."
echo "URL появится в логах: ~/Downloads/alta_viral_scanner/alta_scanner.log"
echo ""
echo "Запусти бота:"
echo "  cd ~/Downloads/alta_viral_scanner && python3 main.py"
echo ""
