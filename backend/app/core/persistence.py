from __future__ import annotations

from app.core.db import get_connection
from app.core.types import Role


class ThreadNotFoundError(Exception):
    pass


def create_or_continue_thread(
    *,
    prompt: str,
    mode: str,
    thread_id: int | None = None,
) -> int:
    conn = get_connection()
    try:
        if thread_id is None:
            cursor = conn.execute(
                "INSERT INTO threads (title, mode) VALUES (?, ?)",
                (prompt[:80], mode),
            )
            resolved_thread_id = int(cursor.lastrowid)
        else:
            thread = conn.execute(
                "SELECT id FROM threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
            if thread is None:
                raise ThreadNotFoundError(f"Thread {thread_id} not found.")
            resolved_thread_id = thread_id
            conn.execute(
                "UPDATE threads SET mode = ? WHERE id = ?",
                (mode, resolved_thread_id),
            )

        conn.execute(
            """
            INSERT INTO messages (thread_id, role, provider, model, content, round)
            VALUES (?, ?, NULL, NULL, ?, 0)
            """,
            (resolved_thread_id, Role.USER.value, prompt),
        )
        conn.commit()
        return resolved_thread_id
    finally:
        conn.close()


def latest_user_prompt(thread_id: int) -> str | None:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT content
            FROM messages
            WHERE thread_id = ? AND role = ? AND provider IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (thread_id, Role.USER.value),
        ).fetchone()
        return str(row["content"]) if row else None
    finally:
        conn.close()


def persist_assistant_message(
    *,
    thread_id: int,
    provider: str,
    model: str | None,
    content: str,
    round_number: int,
) -> None:
    if not content.strip():
        return

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO messages (thread_id, role, provider, model, content, round)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                Role.ASSISTANT.value,
                provider,
                model,
                content,
                round_number,
            ),
        )
        conn.commit()
    finally:
        conn.close()
