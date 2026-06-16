from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.types import Message, ProviderName, Role
from app.orchestrator.provider_stream import stream_provider_events
from app.prompts.templates import HUMAN_INTERJECTION_PREFIX, RELAY_CONTINUE


def format_relay_prior(transcript: list[dict[str, str]]) -> str:
    if not transcript:
        return "No model has spoken yet."
    return "\n\n".join(
        f"{item['speaker']}:\n{item['content']}" for item in transcript
    )


def append_human_steer(transcript: list[dict[str, str]], content: str) -> None:
    if content.strip():
        transcript.append(
            {
                "speaker": "human",
                "content": f"{HUMAN_INTERJECTION_PREFIX}{content.strip()}",
            }
        )


async def stream_relay_speaker(
    prompt: str,
    provider: ProviderName,
    transcript: list[dict[str, str]],
    speaker_index: int,
    premium: bool = False,
) -> AsyncIterator[dict[str, object]]:
    prior = format_relay_prior(transcript)
    messages = [
        Message(Role.SYSTEM, RELAY_CONTINUE.format(prior=prior)),
        Message(Role.USER, prompt),
    ]
    content: list[str] = []

    yield {
        "type": "relay_speaker_start",
        "provider": provider.value,
        "speaker_index": speaker_index,
        "round": speaker_index + 1,
    }

    async for event in stream_provider_events(
        provider,
        messages,
        premium,
        round_number=speaker_index + 1,
    ):
        if event["type"] == "delta":
            content.append(str(event["delta"]))
        yield event

    text = "".join(content)
    transcript.append({"speaker": provider.value, "content": text})
    yield {
        "type": "relay_speaker_done",
        "provider": provider.value,
        "speaker_index": speaker_index,
        "round": speaker_index + 1,
        "content": text,
    }
