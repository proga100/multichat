from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.persistence import (
    ThreadNotFoundError,
    create_or_continue_thread,
    latest_user_prompt,
    persist_assistant_message,
)
from app.core.types import Message, ProviderName, Role
from app.orchestrator.compare import COMPARE_PROVIDERS, stream_compare
from app.orchestrator.debate import stream_debate
from app.orchestrator.provider_stream import stream_provider_events
from app.orchestrator.relay import append_human_steer, stream_relay_speaker
from app.orchestrator.supermind import stream_supermind
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
    mode: Literal["compare", "single", "debate", "relay", "supermind"] = "compare"
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
    mode: Literal["compare", "single", "debate", "relay", "supermind"]
    providers: list[ProviderRunInfo]
    rounds: int
    speaker_order: list[ProviderName]


def _sse(payload: dict[str, object]) -> str:
    event_type = str(payload["type"])
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


@router.post("")
async def create_run(request: CreateRunRequest) -> CreateRunResponse:
    providers = (
        list(COMPARE_PROVIDERS)
        if request.mode in {"compare", "debate", "supermind"}
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

    try:
        run_id = create_or_continue_thread(
            prompt=request.prompt,
            mode=request.mode,
            thread_id=request.thread_id,
        )
    except ThreadNotFoundError:
        raise HTTPException(status_code=404, detail="Thread not found.") from None

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
    prompt = latest_user_prompt(run_id)
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
                    persist_assistant_message(
                        thread_id=run_id,
                        provider=key[0],
                        model=resolve_model(ProviderName(key[0]), False),
                        content="".join(collected.get(key, [])),
                        round_number=key[1],
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
                    persist_assistant_message(
                        thread_id=run_id,
                        provider=key[0],
                        model=resolve_model(ProviderName(key[0]), False),
                        content=content,
                        round_number=key[1],
                    )
                elif event_type == "synthesis_delta":
                    synthesis.append(str(event["delta"]))
                    synthesis_provider = str(event["provider"])
                elif event_type == "synthesis_done":
                    provider = synthesis_provider or str(event["provider"])
                    content = "".join(synthesis) or str(event.get("content", ""))
                    persist_assistant_message(
                        thread_id=run_id,
                        provider=provider,
                        model=resolve_model(ProviderName(provider), False),
                        content=content,
                        round_number=int(event["round"]),
                    )

                yield _sse(event)
            yield _sse({"type": "run_done"})
            return

        if mode == "supermind":
            collected: dict[tuple[str, int], list[str]] = {}
            synthesis: list[str] = []
            synthesis_provider = ""
            scribe: list[str] = []
            scribe_provider = ""
            async for event in stream_supermind(prompt):
                if await request.is_disconnected():
                    return

                event_type = str(event["type"])
                if event_type == "delta":
                    key = (str(event["provider"]), int(event["round"]))
                    collected.setdefault(key, []).append(str(event["delta"]))
                elif event_type == "provider_done":
                    key = (str(event["provider"]), int(event["round"]))
                    persist_assistant_message(
                        thread_id=run_id,
                        provider=key[0],
                        model=resolve_model(ProviderName(key[0]), False),
                        content="".join(collected.get(key, [])),
                        round_number=key[1],
                    )
                elif event_type == "synthesis_delta":
                    synthesis.append(str(event["delta"]))
                    synthesis_provider = str(event["provider"])
                elif event_type == "synthesis_done":
                    provider = synthesis_provider or str(event["provider"])
                    persist_assistant_message(
                        thread_id=run_id,
                        provider=provider,
                        model=resolve_model(ProviderName(provider), False),
                        content="".join(synthesis),
                        round_number=int(event["round"]),
                    )
                elif event_type == "scribe_delta":
                    scribe.append(str(event["delta"]))
                    scribe_provider = str(event["provider"])
                elif event_type == "scribe_done":
                    provider = scribe_provider or str(event["provider"])
                    content = "".join(scribe) or str(event.get("content", ""))
                    persist_assistant_message(
                        thread_id=run_id,
                        provider="scribe",
                        model=resolve_model(ProviderName(provider), False),
                        content=content,
                        round_number=int(event["round"]),
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

                persist_assistant_message(
                    thread_id=run_id,
                    provider=provider.value,
                    model=resolve_model(provider, state.premium),
                    content="".join(content),
                    round_number=state.next_index + 1,
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
                persist_assistant_message(
                    thread_id=run_id,
                    provider=provider_name,
                    model=resolve_model(provider_choice, False),
                    content="".join(content),
                    round_number=0,
                )
            yield _sse(event)

        yield _sse({"type": "run_done"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
