from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.db import get_connection

router = APIRouter(prefix="/api/threads", tags=["threads"])


class ThreadSummary(BaseModel):
    id: int
    title: str | None
    mode: str
    created_at: str
    message_count: int
    latest_message: str | None
    latest_at: str | None


class MessageRecord(BaseModel):
    id: int
    thread_id: int
    role: str
    provider: str | None
    model: str | None
    content: str
    round: int | None
    prompt_tokens: int | None
    output_tokens: int | None
    created_at: str


class ThreadDetail(BaseModel):
    id: int
    title: str | None
    mode: str
    created_at: str
    messages: list[MessageRecord]


def list_threads() -> list[ThreadSummary]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                t.id,
                t.title,
                t.mode,
                t.created_at,
                COUNT(m.id) AS message_count,
                (
                    SELECT content
                    FROM messages
                    WHERE thread_id = t.id
                    ORDER BY id DESC
                    LIMIT 1
                ) AS latest_message,
                (
                    SELECT created_at
                    FROM messages
                    WHERE thread_id = t.id
                    ORDER BY id DESC
                    LIMIT 1
                ) AS latest_at
            FROM threads t
            LEFT JOIN messages m ON m.thread_id = t.id
            GROUP BY t.id
            ORDER BY COALESCE(latest_at, t.created_at) DESC, t.id DESC
            """
        ).fetchall()
        return [ThreadSummary(**dict(row)) for row in rows]
    finally:
        conn.close()


def get_thread(thread_id: int) -> ThreadDetail | None:
    conn = get_connection()
    try:
        thread = conn.execute(
            "SELECT id, title, mode, created_at FROM threads WHERE id = ?",
            (thread_id,),
        ).fetchone()
        if thread is None:
            return None

        messages = conn.execute(
            """
            SELECT id, thread_id, role, provider, model, content, round,
                   prompt_tokens, output_tokens, created_at
            FROM messages
            WHERE thread_id = ?
            ORDER BY id ASC
            """,
            (thread_id,),
        ).fetchall()

        return ThreadDetail(
            **dict(thread),
            messages=[MessageRecord(**dict(message)) for message in messages],
        )
    finally:
        conn.close()


@router.get("")
async def list_thread_summaries() -> list[ThreadSummary]:
    return list_threads()


@router.get("/{thread_id}")
async def get_thread_detail(thread_id: int) -> ThreadDetail:
    thread = get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found.")
    return thread
