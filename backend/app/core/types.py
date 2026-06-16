"""
The shared, provider-agnostic data contract.

Every part of the app speaks in these types. Providers translate THESE into
their own SDK's format inside their own class — nothing else in the app ever
touches provider-specific message shapes. This is what lets you add a 4th model
later by writing a single class.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    SYSTEM = "system"        # instructions / persona. Each provider places this differently.
    USER = "user"
    ASSISTANT = "assistant"


class ProviderName(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"


@dataclass
class Message:
    """One turn in a conversation, in the neutral shared format.

    `role=SYSTEM` is meaningful: providers handle system text in different
    places (Anthropic: top-level `system`; OpenAI: a system message in the
    array; Gemini: `system_instruction`). The translation layer in each
    provider is responsible for putting it where that SDK expects it.
    """
    role: Role
    content: str
