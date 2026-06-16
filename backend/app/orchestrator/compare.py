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


async def _stream_provider(
    provider_name: ProviderName,
    messages: list[Message],
    premium: bool,
    queue: asyncio.Queue[dict[str, object]],
) -> None:
    try:
        async for event in stream_provider_events(provider_name, messages, premium):
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
) -> AsyncIterator[dict[str, object]]:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    tasks = [
        asyncio.create_task(_stream_provider(provider, messages, premium, queue))
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
