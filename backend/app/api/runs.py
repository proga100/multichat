from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.db import get_connection
from app.core.types import Message, ProviderName, Role
from app.orchestrator.compare import COMPARE_PROVIDERS, stream_compare
from app.orchestrator.debate import stream_debate
from app.orchestrator.provider_stream import stream_provider_events
from app.orchestrator.relay import append_human_steer, stream_relay_speaker
from app.providers.factory import resolve_model

router = APIRouter(prefix="/api/runs", tags=["runs"])


@dataclass
class RelayState:
    prompt: str
    order: list[ProviderName]
    premium: bool = False
    pause_between: bool = False
    next_index: int = 0
    awaiting_human: bool = False
    transcript: list[dict[str, str]] = field(default_factory=list)


RELAY_STATES: dict[int, RelayState] = {}


class CreateRunRequest(BaseModel):
    prompt: str = Field(min_length=1)
    thread_id: int | None = None
    mode: Literal["compare", "single", "debate", "relay"] = "compare"
    premium: bool = False
    provider: ProviderName = ProviderName.ANTHROPIC
    rounds: int = Field(default=2, ge=1, le=5)
    speaker_order: list[ProviderName] = Field(default_factory=lambda: list(COMPARE_PROVIDERS))
    pause_between: bool = False


class ProviderRunInfo(BaseModel):
    provider: ProviderName
    model: str


class CreateRunResponse(BaseModel):
    run_id: int
    thread_id: int
    provider: ProviderName
    model: str
    mode: Literal["compare", "single", "debate", "relay"]
    providers: list[ProviderRunInfo]
    rounds: int
    speaker_order: list[ProviderName]


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
            ORDER BY id DESC
            LIMIT 1
            """,
            (run_id, Role.USER.value),
        ).fetchone()
        return str(row["content"]) if row else None
    finally:
        conn.close()


def _persist_assistant_message(
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


@router.post("")
async def create_run(request: CreateRunRequest) -> CreateRunResponse:
    providers = (
        list(COMPARE_PROVIDERS)
        if request.mode in {"compare", "debate"}
        else request.speaker_order
        if request.mode == "relay"
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
        if request.thread_id is None:
            cursor = conn.execute(
                "INSERT INTO threads (title, mode) VALUES (?, ?)",
                (request.prompt[:80], request.mode),
            )
            run_id = int(cursor.lastrowid)
        else:
            thread = conn.execute(
                "SELECT id FROM threads WHERE id = ?",
                (request.thread_id,),
            ).fetchone()
            if thread is None:
                raise HTTPException(status_code=404, detail="Thread not found.")
            run_id = request.thread_id
            conn.execute(
                "UPDATE threads SET mode = ? WHERE id = ?",
                (request.mode, run_id),
            )

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

    if request.mode == "relay":
        RELAY_STATES[run_id] = RelayState(
            prompt=request.prompt,
            order=providers,
            premium=request.premium,
            pause_between=request.pause_between,
        )

    return CreateRunResponse(
        run_id=run_id,
        thread_id=run_id,
        provider=request.provider,
        model=provider_models[0].model,
        mode=request.mode,
        providers=provider_models,
        rounds=request.rounds,
        speaker_order=providers,
    )


class ContinueRunRequest(BaseModel):
    content: str = ""


@router.post("/{run_id}/continue")
async def continue_run(run_id: int, request: ContinueRunRequest) -> dict[str, object]:
    state = RELAY_STATES.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Relay run not found.")
    if not state.awaiting_human:
        raise HTTPException(status_code=409, detail="Run is not awaiting human input.")

    append_human_steer(state.transcript, request.content)
    state.awaiting_human = False
    return {"run_id": run_id, "status": "continued", "next_index": state.next_index}


@router.get("/{run_id}/stream")
async def stream_run(run_id: int, request: Request) -> StreamingResponse:
    prompt = _get_run_prompt(run_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Run not found.")

    async def events() -> AsyncIterator[str]:
        mode = request.query_params.get("mode", "compare")
        rounds = max(1, int(request.query_params.get("rounds", "2")))
        messages = [Message(role=Role.USER, content=prompt)]

        if mode == "compare":
            collected: dict[tuple[str, int], list[str]] = {}
            async for event in stream_compare(messages):
                if await request.is_disconnected():
                    return
                if event["type"] == "delta":
                    key = (str(event["provider"]), int(event["round"]))
                    collected.setdefault(key, []).append(str(event["delta"]))
                elif event["type"] == "provider_done":
                    key = (str(event["provider"]), int(event["round"]))
                    _persist_assistant_message(
                        run_id,
                        key[0],
                        resolve_model(ProviderName(key[0]), False),
                        "".join(collected.get(key, [])),
                        key[1],
                    )
                yield _sse(event)
            yield _sse({"type": "run_done"})
            return

        if mode == "debate":
            collected: dict[tuple[str, int], list[str]] = {}
            synthesis: list[str] = []
            synthesis_provider = ""
            async for event in stream_debate(prompt, rounds):
                if await request.is_disconnected():
                    return

                event_type = str(event["type"])
                if event_type == "delta":
                    key = (str(event["provider"]), int(event["round"]))
                    collected.setdefault(key, []).append(str(event["delta"]))
                elif event_type == "provider_done":
                    key = (str(event["provider"]), int(event["round"]))
                    content = "".join(collected.get(key, []))
                    _persist_assistant_message(
                        run_id,
                        key[0],
                        resolve_model(ProviderName(key[0]), False),
                        content,
                        key[1],
                    )
                elif event_type == "synthesis_delta":
                    synthesis.append(str(event["delta"]))
                    synthesis_provider = str(event["provider"])
                elif event_type == "synthesis_done":
                    provider = synthesis_provider or str(event["provider"])
                    _persist_assistant_message(
                        run_id,
                        provider,
                        resolve_model(ProviderName(provider), False),
                        "".join(synthesis),
                        int(event["round"]),
                    )

                yield _sse(event)
            yield _sse({"type": "run_done"})
            return

        if mode == "relay":
            state = RELAY_STATES.get(run_id)
            if state is None:
                state = RelayState(prompt=prompt, order=list(COMPARE_PROVIDERS))
                RELAY_STATES[run_id] = state

            if state.awaiting_human:
                yield _sse(
                    {
                        "type": "awaiting_human",
                        "run_id": run_id,
                        "next_provider": state.order[state.next_index].value
                        if state.next_index < len(state.order)
                        else None,
                    }
                )
                yield _sse({"type": "run_done"})
                return

            while state.next_index < len(state.order):
                provider = state.order[state.next_index]
                content: list[str] = []
                async for event in stream_relay_speaker(
                    state.prompt,
                    provider,
                    state.transcript,
                    state.next_index,
                    state.premium,
                ):
                    if await request.is_disconnected():
                        return
                    if event["type"] == "delta":
                        content.append(str(event["delta"]))
                    yield _sse(event)

                _persist_assistant_message(
                    run_id,
                    provider.value,
                    resolve_model(provider, state.premium),
                    "".join(content),
                    state.next_index + 1,
                )
                state.next_index += 1

                if state.pause_between and state.next_index < len(state.order):
                    state.awaiting_human = True
                    yield _sse(
                        {
                            "type": "awaiting_human",
                            "run_id": run_id,
                            "next_provider": state.order[state.next_index].value,
                        }
                    )
                    yield _sse({"type": "run_done"})
                    return

            yield _sse({"type": "run_done"})
            return

        try:
            provider_choice = ProviderName(request.query_params.get("provider", "anthropic"))
        except ValueError:
            provider_choice = ProviderName.ANTHROPIC

        provider_name = provider_choice.value
        content: list[str] = []
        async for event in stream_provider_events(provider_choice, messages):
            if await request.is_disconnected():
                return
            if event["type"] == "delta":
                content.append(str(event["delta"]))
            elif event["type"] == "provider_done":
                _persist_assistant_message(
                    run_id,
                    provider_name,
                    resolve_model(provider_choice, False),
                    "".join(content),
                    0,
                )
            yield _sse(event)

        yield _sse({"type": "run_done"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
