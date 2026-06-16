from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.config import settings
from app.core.types import Message, ProviderName
from app.providers.base import ProviderCallError, ProviderConfigurationError
from app.providers.factory import make_provider


def _configured_fallback(requested: ProviderName) -> ProviderName | None:
    if not settings.dev_fallback_enabled:
        return None

    try:
        fallback = ProviderName(settings.dev_provider_fallback)
    except ValueError:
        return None

    if fallback == requested:
        return None

    return fallback


async def _stream_actual_provider(
    event_provider: ProviderName,
    actual_provider: ProviderName,
    messages: list[Message],
    premium: bool,
    round_number: int,
) -> AsyncIterator[dict[str, object]]:
    provider = make_provider(actual_provider, premium=premium)
    fallback_payload = (
        {"fallback_provider": actual_provider.value}
        if actual_provider != event_provider
        else {}
    )

    async for delta in provider.stream(messages):
        yield {
            "type": "delta",
            "provider": event_provider.value,
            "round": round_number,
            "delta": delta,
            **fallback_payload,
        }

    yield {
        "type": "provider_done",
        "provider": event_provider.value,
        "round": round_number,
        **fallback_payload,
    }


async def stream_provider_events(
    provider_name: ProviderName,
    messages: list[Message],
    premium: bool = False,
    round_number: int = 0,
) -> AsyncIterator[dict[str, object]]:
    try:
        async for event in _stream_actual_provider(
            provider_name,
            provider_name,
            messages,
            premium,
            round_number,
        ):
            yield event
        return
    except (ProviderConfigurationError, ProviderCallError) as exc:
        primary_error = str(exc)
    except Exception as exc:
        primary_error = f"{provider_name.value} stream failed: {exc}"

    fallback = _configured_fallback(provider_name)
    if fallback is None:
        yield {
            "type": "error",
            "provider": provider_name.value,
            "round": round_number,
            "message": primary_error,
        }
        return

    yield {
        "type": "fallback_start",
        "provider": provider_name.value,
        "round": round_number,
        "fallback_provider": fallback.value,
        "message": primary_error,
    }

    try:
        async for event in _stream_actual_provider(
            provider_name,
            fallback,
            messages,
            premium,
            round_number,
        ):
            yield event
    except (ProviderConfigurationError, ProviderCallError) as exc:
        yield {
            "type": "error",
            "provider": provider_name.value,
            "round": round_number,
            "message": (
                f"{primary_error}\nFallback {fallback.value} failed: {exc}"
            ),
        }
    except Exception as exc:
        yield {
            "type": "error",
            "provider": provider_name.value,
            "round": round_number,
            "message": (
                f"{primary_error}\nFallback {fallback.value} failed: {exc}"
            ),
        }
