from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.config import settings
from app.core.types import Message, ProviderName, Role
from app.orchestrator.compare import COMPARE_PROVIDERS, stream_compare
from app.orchestrator.provider_stream import stream_provider_events
from app.prompts.templates import SUPERMIND_SCRIBE, SUPERMIND_SYNTHESIS


def _format_individual_answers(answers: dict[ProviderName, str]) -> str:
    return "\n\n".join(
        f"{provider.value}:\n{content or '[no answer]'}"
        for provider, content in answers.items()
    )


async def stream_supermind(
    prompt: str,
    premium: bool = False,
) -> AsyncIterator[dict[str, object]]:
    messages = [Message(role=Role.USER, content=prompt)]
    answers: dict[ProviderName, str] = {}
    collected: dict[ProviderName, list[str]] = {}

    yield {"type": "round_start", "round": 1}
    async for event in stream_compare(messages, premium, COMPARE_PROVIDERS, round_number=1):
        event_type = str(event["type"])
        if event_type == "delta":
            provider = ProviderName(str(event["provider"]))
            collected.setdefault(provider, []).append(str(event["delta"]))
        elif event_type == "provider_done":
            provider = ProviderName(str(event["provider"]))
            answers[provider] = "".join(collected.get(provider, []))
        elif event_type == "error":
            provider = ProviderName(str(event["provider"]))
            answers[provider] = f"[error] {event.get('message', 'Provider failed.')}"

        yield event
    yield {"type": "round_done", "round": 1}

    synthesis_provider = ProviderName(settings.synthesis_provider)
    synthesis_round = 2
    synthesis_messages = [
        Message(
            Role.SYSTEM,
            SUPERMIND_SYNTHESIS.format(answers=_format_individual_answers(answers)),
        ),
        Message(Role.USER, prompt),
    ]
    synthesis_content: list[str] = []

    yield {
        "type": "synthesis_start",
        "provider": synthesis_provider.value,
        "round": synthesis_round,
    }

    async for event in stream_provider_events(
        synthesis_provider,
        synthesis_messages,
        premium,
        synthesis_round,
    ):
        if event["type"] == "delta":
            delta = str(event["delta"])
            synthesis_content.append(delta)
            yield {
                "type": "synthesis_delta",
                "provider": event["provider"],
                "round": synthesis_round,
                "delta": delta,
                **(
                    {"fallback_provider": event["fallback_provider"]}
                    if "fallback_provider" in event
                    else {}
                ),
            }
        elif event["type"] == "provider_done":
            continue
        else:
            yield event

    yield {
        "type": "synthesis_done",
        "provider": synthesis_provider.value,
        "round": synthesis_round,
        "content": "".join(synthesis_content),
    }

    scribe_round = 3
    scribe_content: list[str] = []
    scribe_messages = [
        Message(
            Role.SYSTEM,
            SUPERMIND_SCRIBE.format(
                prompt=prompt,
                answers=_format_individual_answers(answers),
                unified="".join(synthesis_content),
            ),
        ),
        Message(Role.USER, "Write the scribe notes now."),
    ]

    yield {
        "type": "scribe_start",
        "provider": synthesis_provider.value,
        "round": scribe_round,
    }

    async for event in stream_provider_events(
        synthesis_provider,
        scribe_messages,
        premium,
        scribe_round,
    ):
        if event["type"] == "delta":
            delta = str(event["delta"])
            scribe_content.append(delta)
            yield {
                "type": "scribe_delta",
                "provider": event["provider"],
                "round": scribe_round,
                "delta": delta,
                **(
                    {"fallback_provider": event["fallback_provider"]}
                    if "fallback_provider" in event
                    else {}
                ),
            }
        elif event["type"] == "provider_done":
            continue
        else:
            yield event

    yield {
        "type": "scribe_done",
        "provider": synthesis_provider.value,
        "round": scribe_round,
        "content": "".join(scribe_content),
    }
