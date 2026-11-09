"""Chat history + long-term facts, stored in a local SQLite file (data/jim.db)."""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid

from .config import DATA_DIR

DB = DATA_DIR / "jim.db"
_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


with _lock, _conn() as c:
    c.executescript("""
    CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT, created REAL, updated REAL);
    CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conv TEXT, role TEXT,
        content TEXT, meta TEXT, ts REAL);
    CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY AUTOINCREMENT, fact TEXT, ts REAL);
    CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conv);
    """)


def new_conversation(title: str = "New chat") -> str:
    cid = uuid.uuid4().hex[:12]
    now = time.time()
    with _lock, _conn() as c:
        c.execute("INSERT INTO conversations VALUES (?,?,?,?)", (cid, title[:60], now, now))
    return cid


def ensure_conversation(cid: str | None, first_message: str) -> str:
    if cid:
        with _lock, _conn() as c:
            if c.execute("SELECT 1 FROM conversations WHERE id=?", (cid,)).fetchone():
                return cid
    return new_conversation(first_message.strip().split("\n")[0][:60] or "New chat")


def add_message(cid: str, role: str, content: str, meta: str = "") -> None:
    now = time.time()
    with _lock, _conn() as c:
        c.execute("INSERT INTO messages (conv, role, content, meta, ts) VALUES (?,?,?,?,?)", (cid, role, content, meta, now))
        c.execute("UPDATE conversations SET updated=? WHERE id=?", (now, cid))


def history(cid: str, turns: int = 12) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT role, content FROM messages WHERE conv=? AND role IN ('user','assistant') "
                         "ORDER BY id DESC LIMIT ?", (cid, turns * 2)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def conversations(limit: int = 50) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM conversations ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def messages(cid: str) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT role, content, meta, ts FROM messages WHERE conv=? ORDER BY id", (cid,)).fetchall()
    return [dict(r) for r in rows]


def delete_conversation(cid: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM messages WHERE conv=?", (cid,))
        c.execute("DELETE FROM conversations WHERE id=?", (cid,))


def add_fact(fact: str) -> None:
    with _lock, _conn() as c:
        c.execute("INSERT INTO facts (fact, ts) VALUES (?,?)", (fact.strip(), time.time()))


def facts() -> list[dict]:
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM facts ORDER BY id").fetchall()]


def delete_fact(fid: int) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM facts WHERE id=?", (fid,))


def forget_facts(text: str) -> int:
    with _lock, _conn() as c:
        cur = c.execute("DELETE FROM facts WHERE fact LIKE ?", (f"%{text.strip()}%",))
        return cur.rowcount
