"""Council mode: answers -> anonymized peer ranking -> chairman synthesis.

Ported from the "llm-council" idea but adapted to this app's streaming/event
shape and to its anonymization helper. Three stages:

  1. Every model answers in parallel (reuses ``stream_compare``).
  2. Every model ranks the OTHER answers, shown blind as ``Response A/B/C`` so
     peer evaluation can't be swayed by brand or self-preference. The orchestrator
     parses each ``FINAL RANKING:`` block and emits an aggregate ``leaderboard``.
  3. The chairman (``settings.synthesis_provider``) writes one final answer,
     informed by the aggregate standings.

UI events still carry real provider names, so the user always sees who said
what and who won; only the text fed INTO models is anonymized.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import AsyncIterator

from app.core.config import settings
from app.core.types import Message, ProviderName, Role
from app.orchestrator.compare import COMPARE_PROVIDERS, anon_label, stream_compare
from app.orchestrator.provider_stream import stream_provider_events
from app.prompts.templates import (
    COUNCIL_CHAIRMAN,
    COUNCIL_INDIVIDUAL,
    COUNCIL_RANKING,
)

RANKING_ROUND = 2
SYNTHESIS_ROUND = 3
_LABEL_RE = re.compile(r"Response [A-Z]")
_NUMBERED_RE = re.compile(r"\d+\.\s*Response [A-Z]")


def _excerpt(content: str, limit: int = 1500) -> str:
    text = content.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _format_answers(answers: dict[ProviderName, str], max_chars_per_answer: int = 1500) -> str:
    return "\n\n".join(
        f"{anon_label(provider)}:\n{_excerpt(content, max_chars_per_answer) or '[no answer]'}"
        for provider, content in answers.items()
    )


def _parse_ranking(text: str) -> list[str]:
    """Extract ordered ``Response X`` labels (best first) from one reviewer."""
    section = text.split("FINAL RANKING:", 1)[1] if "FINAL RANKING:" in text else text
    numbered = _NUMBERED_RE.findall(section)
    if numbered:
        return [_LABEL_RE.search(match).group() for match in numbered]
    return _LABEL_RE.findall(section)


def _aggregate(
    rankings: list[list[str]],
    label_to_provider: dict[str, ProviderName],
) -> list[dict[str, object]]:
    """Average each answer's position across all reviewers; lower is better."""
    positions: dict[ProviderName, list[int]] = defaultdict(list)
    for parsed in rankings:
        seen: set[str] = set()
        for position, label in enumerate(parsed, start=1):
            provider = label_to_provider.get(label)
            if provider is None or label in seen:
                continue
            seen.add(label)
            positions[provider].append(position)

    standings = [
        {
            "provider": provider.value,
            "label": anon_label(provider),
            "average_rank": round(sum(spots) / len(spots), 2),
            "votes": len(spots),
        }
        for provider, spots in positions.items()
    ]
    standings.sort(key=lambda row: row["average_rank"])
    return standings


async def stream_council(
    prompt: str,
    premium: bool = False,
) -> AsyncIterator[dict[str, object]]:
    # --- Stage 1: independent answers ---------------------------------------
    answer_messages = [
        Message(Role.SYSTEM, COUNCIL_INDIVIDUAL),
        Message(Role.USER, prompt),
    ]
    answers: dict[ProviderName, str] = {}
    collected: dict[ProviderName, list[str]] = {}

    yield {"type": "round_start", "round": 1}
    async for event in stream_compare(answer_messages, premium, COMPARE_PROVIDERS, round_number=1):
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

    # --- Stage 2: anonymized peer ranking -----------------------------------
    answers_block = _format_answers(answers)
    label_to_provider = {anon_label(provider): provider for provider in answers}
    ranking_messages = [
        Message(Role.SYSTEM, COUNCIL_RANKING.format(answers=answers_block)),
        Message(Role.USER, prompt),
    ]
    ranking_texts: dict[ProviderName, str] = {}
    ranking_collected: dict[ProviderName, list[str]] = {}

    yield {"type": "round_start", "round": RANKING_ROUND}
    async for event in stream_compare(
        ranking_messages, premium, COMPARE_PROVIDERS, round_number=RANKING_ROUND
    ):
        event_type = str(event["type"])
        if event_type == "delta":
            provider = ProviderName(str(event["provider"]))
            ranking_collected.setdefault(provider, []).append(str(event["delta"]))
        elif event_type == "provider_done":
            provider = ProviderName(str(event["provider"]))
            ranking_texts[provider] = "".join(ranking_collected.get(provider, []))
        yield event
    yield {"type": "round_done", "round": RANKING_ROUND}

    standings = _aggregate(
        [_parse_ranking(text) for text in ranking_texts.values()],
        label_to_provider,
    )
    yield {
        "type": "leaderboard",
        "round": RANKING_ROUND,
        "standings": standings,
        "label_to_provider": {label: provider.value for label, provider in label_to_provider.items()},
    }

    # --- Stage 3: chairman synthesis ----------------------------------------
    chairman = ProviderName(settings.synthesis_provider)
    standings_text = "\n".join(
        f"{index}. {row['label']} (avg peer rank {row['average_rank']}, {row['votes']} votes)"
        for index, row in enumerate(standings, start=1)
    ) or "No valid rankings were returned; weigh the answers on their merits."
    synthesis_messages = [
        Message(
            Role.SYSTEM,
            COUNCIL_CHAIRMAN.format(answers=answers_block, standings=standings_text),
        ),
        Message(Role.USER, prompt),
    ]
    synthesis_content: list[str] = []

    yield {"type": "synthesis_start", "provider": chairman.value, "round": SYNTHESIS_ROUND}
    async for event in stream_provider_events(chairman, synthesis_messages, premium, SYNTHESIS_ROUND):
        if event["type"] == "delta":
            delta = str(event["delta"])
            synthesis_content.append(delta)
            yield {
                "type": "synthesis_delta",
                "provider": event["provider"],
                "round": SYNTHESIS_ROUND,
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
        "provider": chairman.value,
        "round": SYNTHESIS_ROUND,
        "content": "".join(synthesis_content),
    }
