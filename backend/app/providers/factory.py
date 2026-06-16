"""
Factory: turns a (provider, tier) choice into a ready BaseProvider instance.

Centralises model-string resolution so the default/premium toggle lives in one
place. Callers ask for a provider by name + tier; they never construct provider
classes directly or know model strings.

NOTE: the three concrete providers are imported lazily inside the factory so
that step 1 (scaffold) runs even though only AnthropicProvider exists as a real
implementation yet. As you implement each in steps 2 and 4, they slot in here.
"""
from __future__ import annotations

from app.core.config import settings
from app.core.types import ProviderName
from app.providers.base import BaseProvider


def _resolve_model(provider: ProviderName, premium: bool) -> str:
    """Pick the configured model string for a provider + tier."""
    table = {
        ProviderName.ANTHROPIC: (settings.anthropic_model_default, settings.anthropic_model_premium),
        ProviderName.OPENAI: (settings.openai_model_default, settings.openai_model_premium),
        ProviderName.GEMINI: (settings.gemini_model_default, settings.gemini_model_premium),
    }
    default, prem = table[provider]
    return prem if premium else default


def make_provider(provider: ProviderName, premium: bool = False) -> BaseProvider:
    model = _resolve_model(provider, premium)

    if provider == ProviderName.ANTHROPIC:
        from app.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model)
    if provider == ProviderName.OPENAI:
        from app.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(model)
    if provider == ProviderName.GEMINI:
        from app.providers.gemini_provider import GeminiProvider
        return GeminiProvider(model)

    raise ValueError(f"Unknown provider: {provider}")
