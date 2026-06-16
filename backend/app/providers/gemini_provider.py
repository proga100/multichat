from __future__ import annotations

from collections.abc import AsyncIterator

from google import genai
from google.genai import errors, types

from app.core.config import settings
from app.core.types import Message, ProviderName, Role
from app.providers.base import (
    BaseProvider,
    ProviderCallError,
    ProviderConfigurationError,
)

_GEMINI_ROLES = {
    Role.USER: "user",
    Role.ASSISTANT: "model",
}


class GeminiProvider(BaseProvider):
    name = ProviderName.GEMINI

    def __init__(self, model: str) -> None:
        super().__init__(model)
        if not settings.gemini_api_key:
            raise ProviderConfigurationError("GEMINI_API_KEY is not configured.")
        self._client = genai.Client(api_key=settings.gemini_api_key)

    def _translate_messages(
        self, messages: list[Message]
    ) -> tuple[str | None, list[types.Content]]:
        system_parts: list[str] = []
        contents: list[types.Content] = []

        for message in messages:
            content = message.content.strip()
            if not content:
                continue

            if message.role == Role.SYSTEM:
                system_parts.append(content)
                continue

            role = _GEMINI_ROLES.get(message.role)
            if role is None:
                raise ProviderCallError(f"Unsupported Gemini message role: {message.role}")
            contents.append(types.Content(role=role, parts=[types.Part(text=content)]))

        if not contents:
            raise ProviderCallError("Gemini requires at least one user or model message.")

        system = "\n\n".join(system_parts) if system_parts else None
        return system, contents

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        system, contents = self._translate_messages(messages)
        config = types.GenerateContentConfig(
            maxOutputTokens=settings.gemini_max_output_tokens,
            systemInstruction=system,
        )

        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=config,
            )
            async for chunk in stream:
                text = getattr(chunk, "text", None)
                if text:
                    yield text
        except errors.APIError as exc:
            raise ProviderCallError(f"Gemini stream failed: {exc}") from exc
