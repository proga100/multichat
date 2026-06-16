"""
SQLite persistence — schema + connection helpers.

Single-user, local file. Two tables:
  threads   — one row per conversation.
  messages  — one row per turn. Carries `provider` and `model` (which concrete
              model produced it), `round` (0/NULL for compare, 1..N for debate),
              and nullable token/cost columns (added now while cheap, so the
              ergonomics step later can show spend without a migration).

Full persistence wiring (writing rows during runs, listing/reopening threads)
lands in step 7; this module just defines the schema and gives the rest of the
app a connection. `init_db()` is called on startup.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT,
    mode        TEXT NOT NULL,            -- 'compare' | 'debate' (+ future modes)
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id     INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    role          TEXT NOT NULL,          -- 'user' | 'assistant' | 'system'
    provider      TEXT,                   -- 'anthropic'|'openai'|'gemini'|NULL (user msgs)
    model         TEXT,                   -- concrete model string used, e.g. 'gpt-5-mini'
    content       TEXT NOT NULL,
    round         INTEGER,                -- 0/NULL = compare; 1..N = debate round; synthesis = N+1
    prompt_tokens INTEGER,                -- nullable; filled when provider returns usage
    output_tokens INTEGER,                -- nullable
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id);
"""


def get_connection() -> sqlite3.Connection:
    """A new connection. check_same_thread=False because async handlers may run
    on different threads; we keep usage simple and short-lived per operation."""
    conn = sqlite3.connect(settings.database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
