# Официальный образ Playwright — Chromium уже внутри, скачивать не нужно
# Билд ускоряется с ~5 мин до ~1 мин
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Папка для постоянных данных (Railway Volume)
RUN mkdir -p /data

EXPOSE 5001

CMD ["python", "main.py"]
