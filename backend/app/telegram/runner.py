from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

from app.core.persistence import create_or_continue_thread, persist_assistant_message
from app.core.types import Message, ProviderName, Role
from app.orchestrator.compare import COMPARE_PROVIDERS, stream_compare
from app.orchestrator.debate import stream_debate
from app.orchestrator.relay import stream_relay_speaker
from app.orchestrator.supermind import stream_supermind
from app.providers.factory import resolve_model

TelegramMode = Literal["compare", "debate", "relay", "supermind"]


@dataclass(frozen=True)
class TelegramCommand:
    mode: TelegramMode
    prompt: str
    rounds: int = 2
    premium: bool = False


@dataclass(frozen=True)
class TelegramResult:
    title: str
    body: str


def _format_provider(provider: str) -> str:
    labels = {
        "anthropic": "Anthropic",
        "openai": "OpenAI",
        "gemini": "Gemini",
    }
    return labels.get(provider, provider)


def _excerpt(content: str, max_chars: int) -> str:
    text = " ".join(content.split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1].rstrip()}..."


def _format_answers(answers: dict[str, str], max_chars_per_answer: int = 500) -> str:
    return "\n\n".join(
        (
            f"{_format_provider(provider)}:\n"
            f"{_excerpt(content, max_chars_per_answer) if content else '[no answer]'}"
        )
        for provider, content in answers.items()
    )


async def run_telegram_discussion(
    command: TelegramCommand,
) -> AsyncIterator[TelegramResult]:
    thread_id = create_or_continue_thread(prompt=command.prompt, mode=command.mode)
    yield TelegramResult(
        title=f"Thread #{thread_id}",
        body=f"{command.mode} started.",
    )

    if command.mode == "compare":
        async for result in _run_compare(thread_id, command):
            yield result
        return

    if command.mode == "debate":
        async for result in _run_debate(thread_id, command):
            yield result
        return

    if command.mode == "supermind":
        async for result in _run_supermind(thread_id, command):
            yield result
        return

    async for result in _run_relay(thread_id, command):
        yield result


async def _run_compare(
    thread_id: int,
    command: TelegramCommand,
) -> AsyncIterator[TelegramResult]:
    messages = [Message(role=Role.USER, content=command.prompt)]
    collected: dict[tuple[str, int], list[str]] = {}

    async for event in stream_compare(messages, premium=command.premium):
        event_type = str(event["type"])
        if event_type == "delta":
            key = (str(event["provider"]), int(event["round"]))
            collected.setdefault(key, []).append(str(event["delta"]))
            continue

        if event_type == "provider_done":
            provider = str(event["provider"])
            round_number = int(event["round"])
            content = "".join(collected.get((provider, round_number), []))
            persist_assistant_message(
                thread_id=thread_id,
                provider=provider,
                model=resolve_model(ProviderName(provider), command.premium),
                content=content,
                round_number=round_number,
            )
            yield TelegramResult(
                title=f"Compare: {_format_provider(provider)}",
                body=content or "[no answer]",
            )
            continue

        if event_type == "error":
            yield TelegramResult(
                title=f"Error: {_format_provider(str(event['provider']))}",
                body=str(event.get("message", "Provider failed.")),
            )


async def _run_debate(
    thread_id: int,
    command: TelegramCommand,
) -> AsyncIterator[TelegramResult]:
    collected: dict[tuple[str, int], list[str]] = {}
    round_answers: dict[int, dict[str, str]] = {}
    synthesis: list[str] = []
    synthesis_provider = ""
    scribe: list[str] = []
    scribe_provider = ""

    async for event in stream_debate(
        command.prompt,
        command.rounds,
        premium=command.premium,
    ):
        event_type = str(event["type"])

        if event_type == "delta":
            key = (str(event["provider"]), int(event["round"]))
            collected.setdefault(key, []).append(str(event["delta"]))
            continue

        if event_type == "provider_done":
            provider = str(event["provider"])
            round_number = int(event["round"])
            content = "".join(collected.get((provider, round_number), []))
            persist_assistant_message(
                thread_id=thread_id,
                provider=provider,
                model=resolve_model(ProviderName(provider), command.premium),
                content=content,
                round_number=round_number,
            )
            round_answers.setdefault(round_number, {})[provider] = content
            continue

        if event_type == "round_done":
            round_number = int(event["round"])
            yield TelegramResult(
                title=f"Debate round {round_number} complete",
                body=_format_answers(round_answers.get(round_number, {})),
            )
            continue

        if event_type == "synthesis_delta":
            synthesis.append(str(event["delta"]))
            synthesis_provider = str(event["provider"])
            continue

        if event_type == "synthesis_done":
            provider = synthesis_provider or str(event["provider"])
            content = "".join(synthesis)
            persist_assistant_message(
                thread_id=thread_id,
                provider=provider,
                model=resolve_model(ProviderName(provider), command.premium),
                content=content,
                round_number=int(event["round"]),
            )
            yield TelegramResult(
                title="Synthesis",
                body=content or "[no synthesis]",
            )
            continue

        if event_type == "scribe_delta":
            scribe.append(str(event["delta"]))
            scribe_provider = str(event["provider"])
            continue

        if event_type == "scribe_done":
            provider = scribe_provider or str(event["provider"])
            content = "".join(scribe)
            persist_assistant_message(
                thread_id=thread_id,
                provider="scribe",
                model=resolve_model(ProviderName(provider), command.premium),
                content=content,
                round_number=int(event["round"]),
            )
            yield TelegramResult(
                title="Scribe notes",
                body=content or "[no scribe notes]",
            )
            continue

        if event_type == "error":
            yield TelegramResult(
                title=f"Error: {_format_provider(str(event['provider']))}",
                body=str(event.get("message", "Provider failed.")),
            )


async def _run_supermind(
    thread_id: int,
    command: TelegramCommand,
) -> AsyncIterator[TelegramResult]:
    collected: dict[tuple[str, int], list[str]] = {}
    individual_answers: dict[str, str] = {}
    synthesis: list[str] = []
    synthesis_provider = ""

    async for event in stream_supermind(command.prompt, premium=command.premium):
        event_type = str(event["type"])

        if event_type == "delta":
            key = (str(event["provider"]), int(event["round"]))
            collected.setdefault(key, []).append(str(event["delta"]))
            continue

        if event_type == "provider_done":
            provider = str(event["provider"])
            round_number = int(event["round"])
            content = "".join(collected.get((provider, round_number), []))
            persist_assistant_message(
                thread_id=thread_id,
                provider=provider,
                model=resolve_model(ProviderName(provider), command.premium),
                content=content,
                round_number=round_number,
            )
            individual_answers[provider] = content
            continue

        if event_type == "round_done":
            yield TelegramResult(
                title="Individual responses complete",
                body=_format_answers(individual_answers),
            )
            continue

        if event_type == "synthesis_delta":
            synthesis.append(str(event["delta"]))
            synthesis_provider = str(event["provider"])
            continue

        if event_type == "synthesis_done":
            provider = synthesis_provider or str(event["provider"])
            content = "".join(synthesis)
            persist_assistant_message(
                thread_id=thread_id,
                provider=provider,
                model=resolve_model(ProviderName(provider), command.premium),
                content=content,
                round_number=int(event["round"]),
            )
            yield TelegramResult(
                title="Unified response",
                body=content or "[no unified response]",
            )
            continue

        if event_type == "error":
            yield TelegramResult(
                title=f"Error: {_format_provider(str(event['provider']))}",
                body=str(event.get("message", "Provider failed.")),
            )


async def _run_relay(
    thread_id: int,
    command: TelegramCommand,
) -> AsyncIterator[TelegramResult]:
    transcript: list[dict[str, str]] = []

    for index, provider in enumerate(COMPARE_PROVIDERS):
        async for event in stream_relay_speaker(
            command.prompt,
            provider,
            transcript,
            index,
            command.premium,
        ):
            event_type = str(event["type"])
            if event_type == "relay_speaker_done":
                content = str(event["content"])
                persist_assistant_message(
                    thread_id=thread_id,
                    provider=provider.value,
                    model=resolve_model(provider, command.premium),
                    content=content,
                    round_number=index + 1,
                )
                yield TelegramResult(
                    title=f"Relay: {_format_provider(provider.value)}",
                    body=content or "[no answer]",
                )
            elif event_type == "error":
                yield TelegramResult(
                    title=f"Error: {_format_provider(str(event['provider']))}",
                    body=str(event.get("message", "Provider failed.")),
                )
