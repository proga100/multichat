from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.core.types import Message, ProviderName
from app.orchestrator.provider_stream import stream_provider_events

COMPARE_PROVIDERS = (
    ProviderName.ANTHROPIC,
    ProviderName.OPENAI,
    ProviderName.GEMINI,
)


def anon_label(provider: ProviderName) -> str:
    """Stable anonymized label (Response A/B/C) for a provider.

    Used only when answers are fed back INTO other models (debate critique,
    synthesis, scribe) so peer evaluation can't be swayed by brand or
    self-preference. UI events still carry the real provider name, so the user
    always sees who actually said what.
    """
    try:
        index = COMPARE_PROVIDERS.index(provider)
    except ValueError:
        index = len(COMPARE_PROVIDERS)
    return f"Response {chr(ord('A') + index)}"


async def _stream_provider(
    provider_name: ProviderName,
    messages: list[Message],
    premium: bool,
    round_number: int,
    queue: asyncio.Queue[dict[str, object]],
) -> None:
    try:
        async for event in stream_provider_events(provider_name, messages, premium, round_number):
            await queue.put(event)
    except Exception as exc:
        await queue.put(
            {
                "type": "error",
                "provider": provider_name.value,
                "round": 0,
                "message": f"{provider_name.value} stream failed: {exc}",
            }
        )


async def stream_compare(
    messages: list[Message],
    premium: bool = False,
    providers: tuple[ProviderName, ...] = COMPARE_PROVIDERS,
    round_number: int = 0,
) -> AsyncIterator[dict[str, object]]:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    tasks = [
        asyncio.create_task(_stream_provider(provider, messages, premium, round_number, queue))
        for provider in providers
    ]
    finished = 0

    try:
        while finished < len(tasks):
            event = await queue.get()
            if event["type"] in {"provider_done", "error"}:
                finished += 1
            yield event
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
