"""
OpenAIProvider — STUB (real implementation arrives in step 4).

When implemented it will construct AsyncOpenAI with the key from settings,
translate list[Message] into the OpenAI format (SYSTEM text becomes a system
message in the array), and yield text deltas from the streaming API.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.types import Message, ProviderName
from app.providers.base import BaseProvider


class OpenAIProvider(BaseProvider):
    name = ProviderName.OPENAI

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        raise NotImplementedError(
            "OpenAIProvider.stream not implemented yet — arrives in step 4."
        )
        yield  # pragma: no cover
