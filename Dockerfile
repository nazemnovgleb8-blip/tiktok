FROM python:3.11-slim

# ── Системные зависимости ─────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    wget curl gnupg ca-certificates \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libx11-6 libxext6 \
    fonts-liberation fonts-noto-color-emoji \
    libgl1 libglib2.0-0 libsm6 libxrender1 \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Playwright + Chromium — отдельный слой, кэшируется навсегда ──────────────
# Этот слой НЕ зависит от requirements.txt и кода — пересобирается только при
# явном изменении версии playwright здесь.
RUN pip install playwright==1.49.1
RUN playwright install chromium

# ── Остальные зависимости ─────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Код проекта ───────────────────────────────────────────────────────────────
COPY . .

RUN mkdir -p /data

EXPOSE 5001
CMD ["python", "main.py"]
