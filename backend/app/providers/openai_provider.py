from __future__ import annotations

from collections.abc import AsyncIterator

from openai import APIError, AsyncOpenAI, OpenAIError

from app.core.config import settings
from app.core.types import Message, ProviderName, Role
from app.providers.base import (
    BaseProvider,
    ProviderCallError,
    ProviderConfigurationError,
)

_OPENAI_ROLES = {
    Role.SYSTEM: "system",
    Role.USER: "user",
    Role.ASSISTANT: "assistant",
}


class OpenAIProvider(BaseProvider):
    name = ProviderName.OPENAI

    def __init__(self, model: str) -> None:
        super().__init__(model)
        if not settings.openai_api_key:
            raise ProviderConfigurationError("OPENAI_API_KEY is not configured.")
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    def _translate_messages(self, messages: list[Message]) -> list[dict[str, str]]:
        openai_messages: list[dict[str, str]] = []

        for message in messages:
            content = message.content.strip()
            if not content:
                continue

            role = _OPENAI_ROLES.get(message.role)
            if role is None:
                raise ProviderCallError(f"Unsupported OpenAI message role: {message.role}")
            openai_messages.append({"role": role, "content": content})

        if not openai_messages:
            raise ProviderCallError("OpenAI requires at least one message.")

        return openai_messages

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        try:
            stream = await self._client.responses.create(
                model=self.model,
                input=self._translate_messages(messages),
                max_output_tokens=settings.openai_max_output_tokens,
                stream=True,
            )

            async for event in stream:
                if getattr(event, "type", None) == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield delta
        except (APIError, OpenAIError) as exc:
            raise ProviderCallError(f"OpenAI stream failed: {exc}") from exc
