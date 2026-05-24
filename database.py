"""
database.py — SQLite слой данных
"""
import sqlite3
import os
from datetime import datetime, timedelta

DIR  = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(DIR, "viral.db")


def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS scans (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at    TEXT,
            finished_at   TEXT,
            total_scraped INTEGER DEFAULT 0,
            total_relevant INTEGER DEFAULT 0,
            status        TEXT DEFAULT 'running'
        );

        CREATE TABLE IF NOT EXISTS videos (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id            INTEGER,
            url                TEXT UNIQUE,
            author             TEXT,
            source             TEXT,
            views              INTEGER,
            followers          INTEGER,
            score              REAL,
            category           TEXT DEFAULT 'вирал',
            gemini_relevance   INTEGER DEFAULT 0,
            gemini_hook        TEXT DEFAULT '',
            gemini_why_viral   TEXT DEFAULT '',
            gemini_adaptation  TEXT DEFAULT '',
            gemini_priority    TEXT DEFAULT 'средний',
            created_at         TEXT,
            video_created_at   INTEGER DEFAULT 0,
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        );

        CREATE INDEX IF NOT EXISTS idx_videos_scan   ON videos(scan_id);
        CREATE INDEX IF NOT EXISTS idx_videos_score  ON videos(score DESC);
        CREATE INDEX IF NOT EXISTS idx_videos_url    ON videos(url);
        """)
        # Добавляем колонки если их нет (миграция старых БД)
        existing = {row[1] for row in conn.execute("PRAGMA table_info(videos)")}
        migrations = [
            ("category",        "TEXT DEFAULT 'вирал'"),
            ("gemini_why_viral", "TEXT DEFAULT ''"),
            ("gemini_priority",  "TEXT DEFAULT 'средний'"),
        ]
        migrations = [
            ("category",          "TEXT DEFAULT 'вирал'"),
            ("gemini_why_viral",  "TEXT DEFAULT ''"),
            ("gemini_priority",   "TEXT DEFAULT 'средний'"),
            ("video_created_at",  "INTEGER DEFAULT 0"),
        ]
        for col, coldef in migrations:
            if col not in existing:
                conn.execute(f"ALTER TABLE videos ADD COLUMN {col} {coldef}")


def start_scan() -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO scans (started_at, status) VALUES (?, 'running')",
            (datetime.now().isoformat(),)
        )
        return cur.lastrowid


def finish_scan(scan_id: int, total_scraped: int, total_relevant: int):
    with get_conn() as conn:
        conn.execute(
            """UPDATE scans
               SET finished_at=?, status='done', total_scraped=?, total_relevant=?
               WHERE id=?""",
            (datetime.now().isoformat(), total_scraped, total_relevant, scan_id)
        )


def fail_scan(scan_id: int, error: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE scans SET finished_at=?, status=? WHERE id=?",
            (datetime.now().isoformat(), f"error: {error[:200]}", scan_id)
        )


def save_videos(scan_id: int, videos: list[dict]):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO videos
               (scan_id, url, author, source, views, followers, score,
                created_at, video_created_at)
               VALUES (:scan_id, :url, :author, :source, :views, :followers, :score,
                       :created_at, :video_created_at)""",
            [{
                **v,
                "scan_id":          scan_id,
                "created_at":       now,
                "video_created_at": v.get("video_created_at", 0),
            } for v in videos]
        )


def update_gemini(url: str, relevance: int, hook: str, adaptation: str,
                  category: str = "вирал", why_viral: str = "",
                  priority: str = "средний"):
    with get_conn() as conn:
        conn.execute(
            """UPDATE videos
               SET gemini_relevance=?, gemini_hook=?, gemini_adaptation=?,
                   category=?, gemini_why_viral=?, gemini_priority=?
               WHERE url=?""",
            (relevance, hook, adaptation, category, why_viral, priority, url)
        )


def get_scan_videos(scan_id: int, limit: int = 500) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM videos WHERE scan_id=?
               ORDER BY score DESC LIMIT ?""",
            (scan_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_top_videos(scan_id: int, min_relevance: int = 0, limit: int = 20) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM videos
               WHERE scan_id=? AND gemini_relevance >= ?
               ORDER BY score DESC LIMIT ?""",
            (scan_id, min_relevance, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent_scans(limit: int = 30) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_scan_by_id(scan_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM scans WHERE id=?", (scan_id,)
        ).fetchone()
    return dict(row) if row else None


def get_latest_scan() -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM scans WHERE status='done' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def get_known_urls(days: int = 30) -> set:
    """Возвращает множество URL уже сохранённых за последние N дней.
    Используется для дедупликации между сканами."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT url FROM videos WHERE created_at >= ?", (cutoff,)
        ).fetchall()
    return {row[0] for row in rows}


def get_stats(scan_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT
                COUNT(*) as total,
                MAX(score) as max_score,
                AVG(score) as avg_score,
                SUM(CASE WHEN score >= 500 THEN 1 ELSE 0 END) as ultra,
                SUM(CASE WHEN score >= 100 AND score < 500 THEN 1 ELSE 0 END) as hot,
                SUM(CASE WHEN score >= 20  AND score < 100  THEN 1 ELSE 0 END) as warm,
                SUM(CASE WHEN gemini_relevance >= 7 THEN 1 ELSE 0 END) as relevant
               FROM videos WHERE scan_id=?""",
            (scan_id,)
        ).fetchone()
    return dict(row) if row else {}
