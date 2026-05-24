"""
rescue_viral.py — спасаем пропущенные вирусные видео из последнего скана.

Берёт видео из in-memory данных последнего лога (через re-scan не нужно),
или просто повторно запускает scanner только для получения all_videos и
сохраняет те с score≥50 которых ещё нет в БД.

Запуск: python3 rescue_viral.py
"""
import sqlite3
import asyncio
import sys
import os

DB = os.path.join(os.path.dirname(__file__), "viral.db")
VIRAL_SCORE = 50

def get_existing_urls():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT url FROM videos").fetchall()
    conn.close()
    return {r[0] for r in rows}

def get_latest_scan_id():
    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT id FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return row[0] if row else None

def save_rescued(scan_id, videos):
    from datetime import datetime
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    inserted = 0
    for v in videos:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO videos
                (scan_id, url, author, source, views, followers, score,
                 created_at, video_created_at, passed_filter)
                VALUES (?,?,?,?,?,?,?,?,?,1)
            """, (
                scan_id, v["url"], v["author"], v.get("source",""),
                v["views"], v["followers"], v["score"],
                now, v.get("video_created_at", 0)
            ))
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
        except Exception as e:
            print(f"  Ошибка: {e}")
    conn.commit()
    conn.close()
    return inserted

async def main():
    print("🔍 Запускаю scanner для получения всех собранных видео...")
    print("   (это займёт время — сканер собирает данные заново)\n")

    import config
    import database as db

    db.init()
    cfg = config.load()

    from scanner import run_scan

    def on_progress(msg):
        print(f"  {msg}")

    all_videos, filtered = await run_scan(cfg, on_progress=on_progress)

    print(f"\n📊 Собрано всего: {len(all_videos)}")

    existing = get_existing_urls()
    scan_id  = get_latest_scan_id()

    # Отбираем: score≥50, ещё нет в БД
    to_rescue = [
        v for v in all_videos
        if v["score"] >= VIRAL_SCORE and v["url"] not in existing
    ]

    print(f"💎 Вирусных (score≥{VIRAL_SCORE}) которых нет в БД: {len(to_rescue)}")

    if not to_rescue:
        print("Всё уже в базе — нечего добавлять.")
        return

    # Показываем топ-20
    to_rescue.sort(key=lambda x: x["score"], reverse=True)
    print("\nТоп-20 найденных:")
    for i, v in enumerate(to_rescue[:20], 1):
        print(f"  {i:2}. {v['score']:.0f}x  @{v['author']}  {v['views']:,} просмотров  {v['url']}")

    print(f"\nСохраняю {len(to_rescue)} видео в скан #{scan_id}...")
    saved = save_rescued(scan_id, to_rescue)
    print(f"✅ Сохранено: {saved} новых видео")

    # Синхронизируем на Railway
    sync = input("\nСинхронизировать на Railway? (y/n): ").strip().lower()
    if sync == "y":
        import requests
        url  = cfg.get("dashboard_url","").rstrip("/") + "/api/ingest"
        tok  = cfg.get("sync_token","")
        scan = {"id": scan_id, "started_at": "", "finished_at": "",
                "total_scraped": len(all_videos), "total_relevant": len(to_rescue),
                "status": "done"}
        resp = requests.post(url, json={"scan": scan, "videos": to_rescue},
                             headers={"Authorization": f"Bearer {tok}"}, timeout=60)
        print(f"Railway: {resp.status_code} {resp.json()}")

if __name__ == "__main__":
    asyncio.run(main())
