"""Anthropic provider implementation."""
from __future__ import annotations

from collections.abc import AsyncIterator

from anthropic import AnthropicError, AsyncAnthropic

from app.core.config import settings
from app.core.types import Message, ProviderName, Role
from app.providers.base import (
    BaseProvider,
    ProviderCallError,
    ProviderConfigurationError,
)

_ANTHROPIC_ROLES = {
    Role.USER: "user",
    Role.ASSISTANT: "assistant",
}


class AnthropicProvider(BaseProvider):
    name = ProviderName.ANTHROPIC

    def __init__(self, model: str) -> None:
        super().__init__(model)
        if not settings.anthropic_api_key:
            raise ProviderConfigurationError("ANTHROPIC_API_KEY is not configured.")
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    def _translate_messages(self, messages: list[Message]) -> tuple[str | None, list[dict[str, str]]]:
        system_parts: list[str] = []
        anthropic_messages: list[dict[str, str]] = []

        for message in messages:
            content = message.content.strip()
            if not content:
                continue

            if message.role == Role.SYSTEM:
                system_parts.append(content)
                continue

            role = _ANTHROPIC_ROLES.get(message.role)
            if role is None:
                raise ProviderCallError(f"Unsupported Anthropic message role: {message.role}")
            anthropic_messages.append({"role": role, "content": content})

        if not anthropic_messages:
            raise ProviderCallError("Anthropic requires at least one user or assistant message.")

        system = "\n\n".join(system_parts) if system_parts else None
        return system, anthropic_messages

    def _create_args(self, messages: list[Message]) -> dict[str, object]:
        system, anthropic_messages = self._translate_messages(messages)
        create_args: dict[str, object] = {
            "model": self.model,
            "max_tokens": settings.anthropic_max_tokens,
            "messages": anthropic_messages,
        }
        if system is not None:
            create_args["system"] = system
        return create_args

    async def complete(self, messages: list[Message]) -> str:
        create_args = self._create_args(messages)

        try:
            response = await self._client.messages.create(**create_args)
        except AnthropicError as exc:
            raise ProviderCallError(f"Anthropic request failed: {exc}") from exc

        text_parts: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text = getattr(block, "text", "")
                if text:
                    text_parts.append(text)

        return "".join(text_parts)

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        create_args = self._create_args(messages)

        try:
            async with self._client.messages.stream(**create_args) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield text
        except AnthropicError as exc:
            raise ProviderCallError(f"Anthropic stream failed: {exc}") from exc
