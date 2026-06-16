from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.db import get_connection
from app.core.types import Message, ProviderName, Role
from app.orchestrator.compare import COMPARE_PROVIDERS, stream_compare
from app.providers.base import ProviderCallError, ProviderConfigurationError
from app.providers.factory import make_provider, resolve_model

router = APIRouter(prefix="/api/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    prompt: str = Field(min_length=1)
    mode: Literal["compare", "single"] = "compare"
    premium: bool = False
    provider: ProviderName = ProviderName.ANTHROPIC


class ProviderRunInfo(BaseModel):
    provider: ProviderName
    model: str


class CreateRunResponse(BaseModel):
    run_id: int
    provider: ProviderName
    model: str
    mode: Literal["compare", "single"]
    providers: list[ProviderRunInfo]


def _sse(payload: dict[str, object]) -> str:
    event_type = str(payload["type"])
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


def _get_run_prompt(run_id: int) -> str | None:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT content
            FROM messages
            WHERE thread_id = ? AND role = ? AND provider IS NULL
            ORDER BY id ASC
            LIMIT 1
            """,
            (run_id, Role.USER.value),
        ).fetchone()
        return str(row["content"]) if row else None
    finally:
        conn.close()


@router.post("")
async def create_run(request: CreateRunRequest) -> CreateRunResponse:
    providers = (
        list(COMPARE_PROVIDERS)
        if request.mode == "compare"
        else [request.provider]
    )
    provider_models = [
        ProviderRunInfo(
            provider=provider,
            model=resolve_model(provider, request.premium),
        )
        for provider in providers
    ]

    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO threads (title, mode) VALUES (?, ?)",
            (request.prompt[:80], request.mode),
        )
        run_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO messages (thread_id, role, provider, model, content, round)
            VALUES (?, ?, NULL, NULL, ?, 0)
            """,
            (run_id, Role.USER.value, request.prompt),
        )
        conn.commit()
    finally:
        conn.close()

    return CreateRunResponse(
        run_id=run_id,
        provider=request.provider,
        model=provider_models[0].model,
        mode=request.mode,
        providers=provider_models,
    )


@router.get("/{run_id}/stream")
async def stream_run(run_id: int, request: Request) -> StreamingResponse:
    prompt = _get_run_prompt(run_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Run not found.")

    async def events() -> AsyncIterator[str]:
        mode = request.query_params.get("mode", "compare")
        messages = [Message(role=Role.USER, content=prompt)]

        if mode == "compare":
            async for event in stream_compare(messages):
                if await request.is_disconnected():
                    return
                yield _sse(event)
            yield _sse({"type": "run_done"})
            return

        try:
            provider_choice = ProviderName(request.query_params.get("provider", "anthropic"))
        except ValueError:
            provider_choice = ProviderName.ANTHROPIC

        provider_name = provider_choice.value
        try:
            provider = make_provider(provider_choice)

            async for delta in provider.stream(messages):
                if await request.is_disconnected():
                    return
                yield _sse(
                    {
                        "type": "delta",
                        "provider": provider_name,
                        "round": 0,
                        "delta": delta,
                    }
                )

            yield _sse({"type": "provider_done", "provider": provider_name, "round": 0})
        except (ProviderConfigurationError, ProviderCallError) as exc:
            yield _sse(
                {
                    "type": "error",
                    "provider": provider_name,
                    "round": 0,
                    "message": str(exc),
                }
            )

        yield _sse({"type": "run_done"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
