"""Слой данных: SQLite через aiosqlite. Одна общая коннекция на процесс."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiosqlite

from config import DB_PATH, MATCH_TTL_HOURS

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY,
    username     TEXT,
    name         TEXT,
    age          INTEGER,
    gender       TEXT,
    seek         TEXT,
    city         TEXT,
    answers      TEXT DEFAULT '{}',
    interests    TEXT DEFAULT '[]',
    photo_id     TEXT,
    voice_id     TEXT,
    verified     INTEGER DEFAULT 0,
    is_admin      INTEGER DEFAULT 0,
    is_banned    INTEGER DEFAULT 0,
    is_hidden    INTEGER DEFAULT 0,
    likes_day    INTEGER DEFAULT 0,
    likes_left   INTEGER DEFAULT 40,
    matches_cnt  INTEGER DEFAULT 0,
    created_at   TEXT,
    last_active  TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS fsm (
    key   TEXT PRIMARY KEY,
    state TEXT,
    data  TEXT
);

CREATE TABLE IF NOT EXISTS heartbeat (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    ts TEXT
);

CREATE TABLE IF NOT EXISTS likes (
    from_id    INTEGER NOT NULL,
    to_id      INTEGER NOT NULL,
    created_at TEXT,
    PRIMARY KEY (from_id, to_id)
);

CREATE TABLE IF NOT EXISTS seen (
    viewer_id  INTEGER NOT NULL,
    target_id  INTEGER NOT NULL,
    created_at TEXT,
    PRIMARY KEY (viewer_id, target_id)
);

CREATE TABLE IF NOT EXISTS matches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    a_id       INTEGER NOT NULL,
    b_id       INTEGER NOT NULL,
    created_at TEXT,
    expires_at TEXT,
    unlocked   INTEGER DEFAULT 0,
    closed     INTEGER DEFAULT 0,
    closed_reason TEXT,
    last_msg_at TEXT
);

CREATE TABLE IF NOT EXISTS quest_answers (
    match_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    q_index    INTEGER NOT NULL,
    answer     TEXT NOT NULL,
    created_at TEXT,
    PRIMARY KEY (match_id, user_id, q_index)
);

CREATE TABLE IF NOT EXISTS reports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id    INTEGER NOT NULL,
    to_id      INTEGER NOT NULL,
    reason     TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS ratings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id    INTEGER NOT NULL,
    to_id      INTEGER NOT NULL,
    score      INTEGER NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id   INTEGER NOT NULL,
    from_id    INTEGER NOT NULL,
    to_id      INTEGER NOT NULL,
    msg_id     INTEGER NOT NULL,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_likes_to ON likes(to_id);
CREATE INDEX IF NOT EXISTS idx_matches_a ON matches(a_id);
CREATE INDEX IF NOT EXISTS idx_matches_b ON matches(b_id);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


_conn: Optional[aiosqlite.Connection] = None


async def init(path: str = DB_PATH) -> None:
    global _conn
    _conn = await aiosqlite.connect(path)
    _conn.row_factory = aiosqlite.Row
    await _conn.executescript(SCHEMA)
    await _conn.executescript(NEWS_SCHEMA)
    await migrate()
    await _conn.commit()


async def close() -> None:
    if _conn is not None:
        await _conn.close()


def conn() -> aiosqlite.Connection:
    if _conn is None:
        raise RuntimeError("DB не инициализирована: вызови db.init()")
    return _conn


async def fetchone(sql: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
    async with conn().execute(sql, params) as cur:
        return await cur.fetchone()


async def fetchall(sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
    async with conn().execute(sql, params) as cur:
        return list(await cur.fetchall())


async def execute(sql: str, params: tuple = ()) -> None:
    await conn().execute(sql, params)
    await conn().commit()


# ───────────────────────────── users ─────────────────────────────
async def get_user(uid: int) -> Optional[dict[str, Any]]:
    row = await fetchone("SELECT * FROM users WHERE id = ?", (uid,))
    return dict(row) if row else None


async def migrate() -> None:
    """Мягкие миграции для уже существующих баз."""
    cols = {r["name"] for r in await fetchall("PRAGMA table_info(users)")}
    if "is_admin" not in cols:
        await execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")


async def ensure_user(uid: int, username: str | None) -> dict[str, Any]:
    user = await get_user(uid)
    if user is None:
        await execute(
            "INSERT INTO users (id, username, created_at, last_active) VALUES (?, ?, ?, ?)",
            (uid, username, iso(utcnow()), iso(utcnow())),
        )
        user = await get_user(uid)
    else:
        await execute(
            "UPDATE users SET username = ?, last_active = ? WHERE id = ?",
            (username, iso(utcnow()), uid),
        )
        user["username"] = username
    return user  # type: ignore[return-value]


SETTABLE = {
    "name", "age", "gender", "seek", "city", "photo_id", "voice_id",
    "verified", "is_banned", "is_hidden", "likes_left",
}


async def set_field(uid: int, field: str, value: Any) -> None:
    if field not in SETTABLE:
        raise ValueError(f"Нельзя писать в поле {field}")
    await execute(f"UPDATE users SET {field} = ? WHERE id = ?", (value, uid))


async def set_answers(uid: int, answers: dict[str, str]) -> None:
    await execute(
        "UPDATE users SET answers = ? WHERE id = ?",
        (json.dumps(answers, ensure_ascii=False), uid),
    )


async def set_interests(uid: int, interests: list[str]) -> None:
    await execute(
        "UPDATE users SET interests = ? WHERE id = ?",
        (json.dumps(interests, ensure_ascii=False), uid),
    )


def profile_complete(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    return all(user.get(k) for k in ("name", "age", "gender", "seek", "city", "photo_id"))


async def popular_interests(limit: int = 8) -> list[tuple[str, int]]:
    rows = await fetchall("SELECT interests FROM users WHERE interests != '[]'")
    counter: dict[str, int] = {}
    for row in rows:
        for tag in json.loads(row["interests"] or "[]"):
            counter[tag] = counter.get(tag, 0) + 1
    return sorted(counter.items(), key=lambda kv: -kv[1])[:limit]


# ───────────────────────────── likes / feed ─────────────────────────────
async def save_like(from_id: int, to_id: int) -> bool:
    """Возвращает True, если это взаимный лайк."""
    await execute(
        "INSERT OR IGNORE INTO likes (from_id, to_id, created_at) VALUES (?, ?, ?)",
        (from_id, to_id, iso(utcnow())),
    )
    mutual = await fetchone(
        "SELECT 1 FROM likes WHERE from_id = ? AND to_id = ?", (to_id, from_id)
    )
    return mutual is not None


async def save_seen(viewer_id: int, target_id: int) -> None:
    await execute(
        "INSERT OR IGNORE INTO seen (viewer_id, target_id, created_at) VALUES (?, ?, ?)",
        (viewer_id, target_id, iso(utcnow())),
    )


async def next_candidate(uid: int, seek: str, city: str | None) -> Optional[dict[str, Any]]:
    """Следующая анкета: не я, не лайкнутые, не просмотренные, не в бане."""
    rows = await fetchall(
        """
        SELECT u.* FROM users u
        WHERE u.id != ?
          AND u.gender = ?
          AND u.is_banned = 0
          AND u.is_hidden = 0
          AND u.name IS NOT NULL
          AND u.photo_id IS NOT NULL
          AND u.answers IS NOT NULL AND u.answers != '{}'
          AND u.id NOT IN (SELECT to_id FROM likes WHERE from_id = ?)
          AND u.id NOT IN (SELECT target_id FROM seen WHERE viewer_id = ?)
        ORDER BY (u.city = ?) DESC, u.last_active DESC
        LIMIT 1
        """,
        (uid, seek, uid, uid, city or ""),
    )
    return dict(rows[0]) if rows else None


async def who_liked_me(uid: int) -> list[dict[str, Any]]:
    rows = await fetchall(
        """
        SELECT u.* FROM likes l JOIN users u ON u.id = l.from_id
        WHERE l.to_id = ? AND u.is_banned = 0
          AND l.from_id NOT IN (SELECT to_id FROM likes WHERE from_id = ?)
        ORDER BY l.created_at DESC
        """,
        (uid, uid),
    )
    return [dict(r) for r in rows]


async def likes_today(uid: int) -> int:
    start = iso(utcnow().replace(hour=0, minute=0, second=0, microsecond=0))
    row = await fetchone(
        "SELECT COUNT(*) AS c FROM likes WHERE from_id = ? AND created_at >= ?", (uid, start)
    )
    return int(row["c"]) if row else 0


# ───────────────────────────── matches ─────────────────────────────
async def create_match(a_id: int, b_id: int) -> int:
    now = utcnow()
    await execute(
        """INSERT INTO matches (a_id, b_id, created_at, expires_at)
           VALUES (?, ?, ?, ?)""",
        (a_id, b_id, iso(now), iso(now + timedelta(hours=MATCH_TTL_HOURS))),
    )
    row = await fetchone("SELECT last_insert_rowid() AS id")
    mid = int(row["id"])  # type: ignore[index]
    await execute("UPDATE users SET matches_cnt = matches_cnt + 1 WHERE id IN (?, ?)", (a_id, b_id))
    return mid


async def get_match(mid: int) -> Optional[dict[str, Any]]:
    row = await fetchone("SELECT * FROM matches WHERE id = ?", (mid,))
    return dict(row) if row else None


async def find_match_between(a: int, b: int) -> Optional[dict[str, Any]]:
    row = await fetchone(
        """SELECT * FROM matches WHERE closed = 0
           AND ((a_id = ? AND b_id = ?) OR (a_id = ? AND b_id = ?))""",
        (a, b, b, a),
    )
    return dict(row) if row else None


async def user_matches(uid: int, include_closed: bool = False) -> list[dict[str, Any]]:
    sql = """SELECT m.*, p.name AS partner_name, p.id AS partner_id
             FROM matches m
             JOIN users p ON p.id = CASE WHEN m.a_id = ? THEN m.b_id ELSE m.a_id END
             WHERE (m.a_id = ? OR m.b_id = ?)"""
    if not include_closed:
        sql += " AND m.closed = 0"
    sql += " ORDER BY m.unlocked DESC, m.created_at DESC"
    rows = await fetchall(sql, (uid, uid, uid))
    return [dict(r) for r in rows]


async def first_open_match(uid: int) -> Optional[dict[str, Any]]:
    """Единственный открытый чат пользователя — чтобы понимать, куда роутить сообщение."""
    open_matches = [m for m in await user_matches(uid) if m["unlocked"]]
    return open_matches[0] if len(open_matches) == 1 else None


async def touch_match(mid: int) -> None:
    await execute("UPDATE matches SET last_msg_at = ? WHERE id = ?", (iso(utcnow()), mid))


async def unlock_match(mid: int) -> None:
    await execute("UPDATE matches SET unlocked = 1 WHERE id = ?", (mid,))


async def close_match(mid: int, reason: str = "expired") -> None:
    await execute(
        "UPDATE matches SET closed = 1, closed_reason = ? WHERE id = ?", (reason, mid)
    )


async def expire_matches() -> list[dict[str, Any]]:
    """Сжигает мэтчи, где за TTL часов не было ни одного сообщения."""
    now = iso(utcnow())
    rows = await fetchall(
        "SELECT * FROM matches WHERE closed = 0 AND last_msg_at IS NULL AND expires_at < ?", (now,)
    )
    for row in rows:
        await close_match(int(row["id"]), "expired")
    return [dict(r) for r in rows]


# ───────────────────────────── ледокол ─────────────────────────────
async def save_quest_answer(mid: int, uid: int, idx: int, answer: str) -> None:
    await execute(
        """INSERT OR REPLACE INTO quest_answers (match_id, user_id, q_index, answer, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (mid, uid, idx, answer, iso(utcnow())),
    )


async def quest_answer(mid: int, uid: int, idx: int) -> Optional[str]:
    row = await fetchone(
        "SELECT answer FROM quest_answers WHERE match_id = ? AND user_id = ? AND q_index = ?",
        (mid, uid, idx),
    )
    return row["answer"] if row else None


async def quest_progress(mid: int, uid: int) -> int:
    row = await fetchone(
        "SELECT COUNT(*) AS c FROM quest_answers WHERE match_id = ? AND user_id = ?", (mid, uid)
    )
    return int(row["c"]) if row else 0


# ───────────────────────────── модерация / статы ─────────────────────────────
async def add_report(from_id: int, to_id: int, reason: str) -> None:
    await execute(
        "INSERT INTO reports (from_id, to_id, reason, created_at) VALUES (?, ?, ?, ?)",
        (from_id, to_id, reason, iso(utcnow())),
    )


async def heartbeat() -> None:
    await execute(
        "INSERT INTO heartbeat (id, ts) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET ts = excluded.ts",
        (iso(utcnow()),),
    )


async def last_heartbeat() -> Optional[str]:
    row = await fetchone("SELECT ts FROM heartbeat WHERE id = 1")
    return row["ts"] if row else None


async def stats() -> dict[str, int]:
    out: dict[str, int] = {}
    for key, sql in {
        "users": "SELECT COUNT(*) c FROM users",
        "profiles": "SELECT COUNT(*) c FROM users WHERE photo_id IS NOT NULL AND answers != '{}'",
        "likes": "SELECT COUNT(*) c FROM likes",
        "matches": "SELECT COUNT(*) c FROM matches",
        "chats": "SELECT COUNT(*) c FROM matches WHERE unlocked = 1",
        "reports": "SELECT COUNT(*) c FROM reports",
        "banned": "SELECT COUNT(*) c FROM users WHERE is_banned = 1",
    }.items():
        row = await fetchone(sql)
        out[key] = int(row["c"]) if row else 0
    return out


# ───────────────────────────── сообщения чата ─────────────────────────────
async def save_message(match_id: int, from_id: int, to_id: int, msg_id: int) -> None:
    await execute(
        """INSERT INTO messages (match_id, from_id, to_id, msg_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (match_id, from_id, to_id, msg_id, iso(utcnow())),
    )


async def find_relay(to_id: int, msg_at_recipient: int) -> Optional[dict[str, Any]]:
    """По reply на сообщение бота находит, кто отправитель, и в каком мэтче."""
    row = await fetchone(
        "SELECT * FROM messages WHERE to_id = ? AND msg_id = ?", (to_id, msg_at_recipient)
    )
    return dict(row) if row else None


# ═══════════════════════════ ЛЕНТА (контент) ═══════════════════════════

NEWS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topic        TEXT NOT NULL,
    name         TEXT NOT NULL,
    url          TEXT NOT NULL UNIQUE,
    active       INTEGER DEFAULT 1,
    last_fetched TEXT,
    fail_count   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS articles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    topic         TEXT NOT NULL,
    source_name   TEXT,
    url_hash      TEXT NOT NULL UNIQUE,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    summary       TEXT,
    image_url     TEXT,
    published_at  TEXT,
    fetched_at    TEXT,
    likes         INTEGER DEFAULT 0,
    shares        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_topics (
    user_id  INTEGER NOT NULL,
    topic    TEXT NOT NULL,
    PRIMARY KEY (user_id, topic)
);

CREATE TABLE IF NOT EXISTS article_marks (
    user_id    INTEGER NOT NULL,
    article_id INTEGER NOT NULL,
    action     TEXT NOT NULL,          -- seen | saved | shared
    created_at TEXT,
    PRIMARY KEY (user_id, article_id, action)
);

CREATE TABLE IF NOT EXISTS shares (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id   INTEGER NOT NULL,
    from_id    INTEGER NOT NULL,
    to_id      INTEGER NOT NULL,
    article_id INTEGER NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS digest_log (
    user_id INTEGER NOT NULL,
    day     TEXT NOT NULL,
    PRIMARY KEY (user_id, day)
);

CREATE INDEX IF NOT EXISTS idx_articles_topic ON articles(topic, published_at);
CREATE INDEX IF NOT EXISTS idx_marks_user ON article_marks(user_id);
"""


async def init_news() -> None:
    await conn().executescript(NEWS_SCHEMA)
    await conn().commit()


# ── темы ──
async def get_user_topics(uid: int) -> list[str]:
    rows = await fetchall("SELECT topic FROM user_topics WHERE user_id = ?", (uid,))
    return [r["topic"] for r in rows]


async def set_user_topics(uid: int, topics: list[str]) -> None:
    await execute("DELETE FROM user_topics WHERE user_id = ?", (uid,))
    for topic in topics:
        await execute(
            "INSERT OR IGNORE INTO user_topics (user_id, topic) VALUES (?, ?)", (uid, topic)
        )


# ── источники ──
async def get_meta(key: str) -> Optional[str]:
    row = await fetchone("SELECT value FROM meta WHERE key = ?", (key,))
    return row["value"] if row else None


async def set_meta(key: str, value: str) -> None:
    await execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


async def wipe_news() -> None:
    """Полная зачистка ленты: меняем контент-набор — старое не должно всплывать."""
    for table in ("article_marks", "shares", "articles", "sources"):
        await execute(f"DELETE FROM {table}")


async def deactivate_sources_except(urls: list[str]) -> None:
    """Гасим источники, которых нет в актуальном списке (иначе тянут старое)."""
    if not urls:
        return
    placeholders = ",".join("?" for _ in urls)
    await execute(
        f"UPDATE sources SET active = 0 WHERE url NOT IN ({placeholders})", tuple(urls)
    )


async def seed_sources(seeds: list[tuple[str, str, str]]) -> int:
    added = 0
    for topic, name, url in seeds:
        row = await fetchone("SELECT id FROM sources WHERE url = ?", (url,))
        if row is None:
            await execute(
                "INSERT INTO sources (topic, name, url) VALUES (?, ?, ?)", (topic, name, url)
            )
            added += 1
    return added


async def sources_to_fetch(min_interval_minutes: int = 30) -> list[dict[str, Any]]:
    cutoff = iso(utcnow() - timedelta(minutes=min_interval_minutes))
    rows = await fetchall(
        """SELECT * FROM sources WHERE active = 1
           AND (last_fetched IS NULL OR last_fetched < ?) AND fail_count < 5""",
        (cutoff,),
    )
    return [dict(r) for r in rows]


async def mark_source(source_id: int, ok: bool) -> None:
    if ok:
        await execute(
            "UPDATE sources SET last_fetched = ?, fail_count = 0 WHERE id = ?",
            (iso(utcnow()), source_id),
        )
    else:
        await execute(
            "UPDATE sources SET last_fetched = ?, fail_count = fail_count + 1 WHERE id = ?",
            (iso(utcnow()), source_id),
        )


# ── статьи ──
async def add_article(
    topic: str,
    source_name: str,
    url_hash: str,
    url: str,
    title: str,
    summary: str,
    image_url: str | None,
    published_at: str | None,
) -> bool:
    """True, если статья новая (дедуп по url_hash)."""
    row = await fetchone("SELECT id FROM articles WHERE url_hash = ?", (url_hash,))
    if row:
        return False
    await execute(
        """INSERT INTO articles
           (topic, source_name, url_hash, url, title, summary, image_url, published_at, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            topic, source_name, url_hash, url, title, summary, image_url,
            published_at or iso(utcnow()), iso(utcnow()),
        ),
    )
    return True


async def articles_for_user(uid: int, topics: list[str], hours: int = 72, limit: int = 40):
    if not topics:
        return []
    placeholders = ",".join("?" for _ in topics)
    rows = await fetchall(
        f"""SELECT a.* FROM articles a
            WHERE a.topic IN ({placeholders})
              AND a.fetched_at >= ?
              AND a.id NOT IN (SELECT article_id FROM article_marks WHERE user_id = ?)
            ORDER BY a.published_at DESC LIMIT ?""",
        (*topics, iso(utcnow() - timedelta(hours=hours)), uid, limit),
    )
    return [dict(r) for r in rows]


async def get_article(article_id: int) -> Optional[dict[str, Any]]:
    row = await fetchone("SELECT * FROM articles WHERE id = ?", (article_id,))
    return dict(row) if row else None


async def mark_article(uid: int, article_id: int, action: str) -> None:
    await execute(
        """INSERT OR IGNORE INTO article_marks (user_id, article_id, action, created_at)
           VALUES (?, ?, ?, ?)""",
        (uid, article_id, action, iso(utcnow())),
    )
    if action == "saved":
        await execute("UPDATE articles SET likes = likes + 1 WHERE id = ?", (article_id,))


async def saved_articles(uid: int, limit: int = 10) -> list[dict[str, Any]]:
    rows = await fetchall(
        """SELECT a.* FROM article_marks m JOIN articles a ON a.id = m.article_id
           WHERE m.user_id = ? AND m.action = 'saved'
           ORDER BY m.created_at DESC LIMIT ?""",
        (uid, limit),
    )
    return [dict(r) for r in rows]


async def log_share(match_id: int, from_id: int, to_id: int, article_id: int) -> None:
    await execute(
        """INSERT INTO shares (match_id, from_id, to_id, article_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (match_id, from_id, to_id, article_id, iso(utcnow())),
    )
    await execute("UPDATE articles SET shares = shares + 1 WHERE id = ?", (article_id,))
    await mark_article(from_id, article_id, "shared")


async def common_reading(uid: int, limit: int = 3) -> list[dict[str, Any]]:
    """
    «Вы оба это читали»: статьи, которые пользователь и его партнёр по мэтчу
    сохранили/шернули. Самый сильный повод написать первым.
    """
    rows = await fetchall(
        """
        SELECT a.*, m.id AS match_id, p.id AS partner_id, p.name AS partner_name
        FROM matches m
        JOIN users p ON p.id = CASE WHEN m.a_id = ? THEN m.b_id ELSE m.a_id END
        JOIN article_marks mine ON mine.user_id = ?
        JOIN article_marks theirs
             ON theirs.article_id = mine.article_id AND theirs.user_id = p.id
        JOIN articles a ON a.id = mine.article_id
        WHERE (m.a_id = ? OR m.b_id = ?) AND m.closed = 0
          AND mine.action IN ('saved', 'shared') AND theirs.action IN ('saved', 'shared')
          AND mine.user_id != theirs.user_id
        GROUP BY a.id
        ORDER BY a.published_at DESC
        LIMIT ?
        """,
        (uid, uid, uid, uid, limit),
    )
    return [dict(r) for r in rows]


# ── дневной дайджест ──
async def digest_already_sent(uid: int, day: str) -> bool:
    row = await fetchone("SELECT 1 FROM digest_log WHERE user_id = ? AND day = ?", (uid, day))
    return row is not None


async def mark_digest_sent(uid: int, day: str) -> None:
    await execute("INSERT OR IGNORE INTO digest_log (user_id, day) VALUES (?, ?)", (uid, day))


async def users_for_digest(limit: int = 500) -> list[int]:
    rows = await fetchall(
        """SELECT u.id FROM users u
           WHERE u.is_banned = 0 AND u.photo_id IS NOT NULL
             AND EXISTS (SELECT 1 FROM user_topics t WHERE t.user_id = u.id)
           LIMIT ?""",
        (limit,),
    )
    return [int(r["id"]) for r in rows]
