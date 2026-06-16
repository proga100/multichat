"""
GeminiProvider — STUB (real implementation arrives in step 4).

When implemented it will construct the google-genai client and use its async
surface (client.aio.*), translate list[Message] into the Gemini format (SYSTEM
text goes in `system_instruction`; roles map user->"user", assistant->"model"),
and yield text deltas from the streaming API.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.types import Message, ProviderName
from app.providers.base import BaseProvider


class GeminiProvider(BaseProvider):
    name = ProviderName.GEMINI

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        raise NotImplementedError(
            "GeminiProvider.stream not implemented yet — arrives in step 4."
        )
        yield  # pragma: no cover
