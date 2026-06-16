from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.core.config import settings
from app.core.types import Message, ProviderName, Role
from app.orchestrator.compare import COMPARE_PROVIDERS
from app.orchestrator.provider_stream import stream_provider_events
from app.prompts.templates import DEBATE_CRITIQUE, DEBATE_ROUND1, DEBATE_SYNTHESIS

DEBATE_ROUND1_MAX_CHARS = 900
DEBATE_CRITIQUE_MAX_CHARS = 600
DEBATE_SYNTHESIS_MAX_CHARS = 1000
TRIM_NOTICE = "\n\n[Trimmed for length.]"


def _excerpt(content: str, max_chars: int) -> str:
    text = " ".join(content.split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1].rstrip()}..."


def _format_answers(
    answers: dict[ProviderName, str],
    exclude: ProviderName | None = None,
    max_chars_per_answer: int = 1000,
) -> str:
    blocks: list[str] = []
    for provider, content in answers.items():
        if provider == exclude:
            continue
        formatted = _excerpt(content, max_chars_per_answer) if content else "[no answer]"
        blocks.append(f"{provider.value}:\n{formatted}")
    return "\n\n".join(blocks)


def _round_output_limit(round_number: int) -> int:
    if round_number <= 1:
        return DEBATE_ROUND1_MAX_CHARS
    return DEBATE_CRITIQUE_MAX_CHARS


def _limit_delta(delta: str, emitted_chars: int, max_chars: int) -> tuple[str, bool]:
    remaining = max_chars - emitted_chars
    if remaining <= 0:
        return "", True
    if len(delta) <= remaining:
        return delta, False

    trimmed = delta[:remaining].rstrip()
    if trimmed:
        trimmed = f"{trimmed}{TRIM_NOTICE}"
    return trimmed, True


def _messages_for_round(
    prompt: str,
    provider: ProviderName,
    round_number: int,
    previous_answers: dict[ProviderName, str],
) -> list[Message]:
    if round_number == 1:
        return [
            Message(Role.SYSTEM, DEBATE_ROUND1),
            Message(Role.USER, prompt),
        ]

    own_previous = _excerpt(previous_answers.get(provider, ""), 500)
    others = _format_answers(previous_answers, exclude=provider, max_chars_per_answer=500)
    return [
        Message(Role.SYSTEM, DEBATE_CRITIQUE.format(others=others)),
        Message(Role.USER, prompt),
        Message(Role.ASSISTANT, own_previous),
        Message(Role.USER, f"Continue debate round {round_number}."),
    ]


async def _stream_debate_provider(
    provider: ProviderName,
    messages: list[Message],
    round_number: int,
    premium: bool,
    queue: asyncio.Queue[dict[str, object]],
) -> None:
    content: list[str] = []
    emitted_chars = 0
    max_chars = _round_output_limit(round_number)
    trimmed_for_length = False
    fallback_provider: str | None = None

    async for event in stream_provider_events(provider, messages, premium, round_number):
        if "fallback_provider" in event:
            fallback_provider = str(event["fallback_provider"])

        if event["type"] == "delta":
            delta, should_stop = _limit_delta(str(event["delta"]), emitted_chars, max_chars)
            if delta:
                content.append(delta)
                emitted_chars += len(delta)
                await queue.put({**event, "delta": delta})
            if should_stop:
                trimmed_for_length = True
                break
            continue

        await queue.put(event)

    if trimmed_for_length:
        done_event: dict[str, object] = {
            "type": "provider_done",
            "provider": provider.value,
            "round": round_number,
        }
        if fallback_provider is not None:
            done_event["fallback_provider"] = fallback_provider
        await queue.put(done_event)

    await queue.put(
        {
            "type": "_round_provider_complete",
            "provider": provider.value,
            "round": round_number,
            "content": "".join(content),
        }
    )


async def _stream_round(
    prompt: str,
    round_number: int,
    previous_answers: dict[ProviderName, str],
    premium: bool,
) -> AsyncIterator[dict[str, object]]:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    providers = COMPARE_PROVIDERS
    tasks = [
        asyncio.create_task(
            _stream_debate_provider(
                provider,
                _messages_for_round(prompt, provider, round_number, previous_answers),
                round_number,
                premium,
                queue,
            )
        )
        for provider in providers
    ]
    complete = 0
    answers: dict[ProviderName, str] = {}

    try:
        while complete < len(tasks):
            event = await queue.get()
            if event["type"] == "_round_provider_complete":
                complete += 1
                answers[ProviderName(str(event["provider"]))] = str(event["content"])
                continue
            yield event
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    yield {
        "type": "_round_complete",
        "round": round_number,
        "answers": answers,
    }


async def stream_debate(
    prompt: str,
    rounds: int,
    premium: bool = False,
) -> AsyncIterator[dict[str, object]]:
    previous_answers: dict[ProviderName, str] = {}
    rounds = max(1, rounds)

    for round_number in range(1, rounds + 1):
        yield {"type": "round_start", "round": round_number}
        async for event in _stream_round(prompt, round_number, previous_answers, premium):
            if event["type"] == "_round_complete":
                previous_answers = event["answers"]  # type: ignore[assignment]
                continue
            yield event
        yield {"type": "round_done", "round": round_number}

    synthesis_provider = ProviderName(settings.synthesis_provider)
    synthesis_round = rounds + 1
    answers = _format_answers(previous_answers, max_chars_per_answer=650)
    synthesis_messages = [
        Message(Role.SYSTEM, DEBATE_SYNTHESIS.format(answers=answers)),
        Message(Role.USER, prompt),
    ]
    synthesis_content: list[str] = []

    yield {
        "type": "synthesis_start",
        "provider": synthesis_provider.value,
        "round": synthesis_round,
    }

    async for event in stream_provider_events(
        synthesis_provider,
        synthesis_messages,
        premium,
        synthesis_round,
    ):
        if event["type"] == "delta":
            raw_delta = str(event["delta"])
            delta, should_stop = _limit_delta(
                raw_delta,
                sum(len(part) for part in synthesis_content),
                DEBATE_SYNTHESIS_MAX_CHARS,
            )
            if not delta and should_stop:
                break
            synthesis_content.append(delta)
            yield {
                "type": "synthesis_delta",
                "provider": event["provider"],
                "round": synthesis_round,
                "delta": delta,
                **(
                    {"fallback_provider": event["fallback_provider"]}
                    if "fallback_provider" in event
                    else {}
                ),
            }
            if should_stop:
                break
        elif event["type"] == "provider_done":
            continue
        else:
            yield event

    yield {
        "type": "synthesis_done",
        "provider": synthesis_provider.value,
        "round": synthesis_round,
        "content": "".join(synthesis_content),
    }
