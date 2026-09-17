import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "jobs.db"

CACHE_TTL_JOBS = 86_400       # 24 hours
CACHE_TTL_CONTACTS = 604_800  # 7 days


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                company    TEXT NOT NULL,
                title      TEXT NOT NULL,
                url        TEXT UNIQUE,
                score      INTEGER DEFAULT 0,
                source     TEXT,
                location   TEXT,
                summary    TEXT,
                saved_at   INTEGER DEFAULT (strftime('%s','now'))
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_co_title
                ON jobs(lower(company), lower(title));

            CREATE TABLE IF NOT EXISTS cache (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS applications (
                url             TEXT PRIMARY KEY,
                company         TEXT NOT NULL,
                title           TEXT NOT NULL,
                status          TEXT NOT NULL,
                notes           TEXT DEFAULT '',
                contact_reached INTEGER DEFAULT 0,
                created_at      INTEGER DEFAULT (strftime('%s','now')),
                updated_at      INTEGER DEFAULT (strftime('%s','now'))
            );
            CREATE INDEX IF NOT EXISTS idx_app_status ON applications(status);
        """)


def get_cache(key: str) -> dict | list | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
    if row and row["expires_at"] > int(time.time()):
        return json.loads(row["value"])
    return None


def set_cache(key: str, value: dict | list, ttl: int = CACHE_TTL_JOBS) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), int(time.time()) + ttl),
        )


def save_job(
    company: str,
    title: str,
    url: str,
    score: int = 0,
    source: str = "",
    location: str = "",
    summary: str = "",
) -> bool:
    """Returns True if newly inserted, False if duplicate."""
    try:
        with _conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO jobs
                   (company, title, url, score, source, location, summary)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (company, title, url, score, source, location, summary),
            )
            return conn.execute("SELECT changes()").fetchone()[0] > 0
    except sqlite3.Error:
        return False


def get_saved_jobs(limit: int = 100) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT company, title, url, score, source, location, summary, saved_at
               FROM jobs ORDER BY score DESC, saved_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_saved_urls() -> set[str]:
    with _conn() as conn:
        rows = conn.execute("SELECT url FROM jobs WHERE url IS NOT NULL").fetchall()
    return {r["url"] for r in rows}


def get_saved_company_titles() -> set[tuple[str, str]]:
    with _conn() as conn:
        rows = conn.execute("SELECT company, title FROM jobs").fetchall()
    return {(r["company"].lower(), r["title"].lower()) for r in rows}


def upsert_application(
    url: str,
    company: str,
    title: str,
    status: str,
    notes: str = "",
    contact_reached: bool | None = None,
) -> dict:
    """Insert or update one application. Blank company/title/notes keep old values."""
    now = int(time.time())
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE url = ?", (url,)
        ).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO applications
                   (url, company, title, status, notes, contact_reached,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (url, company, title, status, notes,
                 int(bool(contact_reached)), now, now),
            )
            return {"url": url, "status": status, "created": True}

        conn.execute(
            """UPDATE applications
               SET company = ?, title = ?, status = ?, notes = ?,
                   contact_reached = ?, updated_at = ?
               WHERE url = ?""",
            (
                company or row["company"],
                title or row["title"],
                status,
                notes or row["notes"],
                int(bool(contact_reached)) if contact_reached is not None
                else row["contact_reached"],
                now,
                url,
            ),
        )
        return {
            "url": url,
            "status": status,
            "created": False,
            "previous_status": row["status"],
        }


def get_applications(status: str = "", limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM applications"
    args: tuple = ()
    if status:
        sql += " WHERE status = ?"
        args = (status,)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    with _conn() as conn:
        rows = conn.execute(sql, (*args, limit)).fetchall()
    return [dict(r) for r in rows]


def delete_application(url: str) -> bool:
    with _conn() as conn:
        conn.execute("DELETE FROM applications WHERE url = ?", (url,))
        return conn.execute("SELECT changes()").fetchone()[0] > 0
