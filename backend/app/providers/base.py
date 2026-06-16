"""
The central abstraction. Every model the app talks to is a BaseProvider.

The rest of the application depends ONLY on this interface — it never imports
anthropic/openai/google directly. Adding a new model = writing one subclass
that implements `stream()` (and, for step 2, `complete()`).

Design note: `stream` is the primary method (everything streams in the final
app). `complete` exists mainly so step 2 can verify a provider end-to-end
without the SSE plumbing; it has a default implementation that just drains the
stream, so subclasses only strictly need to implement `stream`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.core.types import Message, ProviderName


class ProviderConfigurationError(RuntimeError):
    """Raised when a provider cannot run because local settings are incomplete."""


class ProviderCallError(RuntimeError):
    """Raised when a provider SDK call fails after configuration succeeds."""


class BaseProvider(ABC):
    #: Which provider this is — set by each subclass.
    name: ProviderName

    def __init__(self, model: str) -> None:
        #: The concrete model string this instance will call (default or premium,
        #: resolved by the factory before construction).
        self.model = model

    @abstractmethod
    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        """Yield text deltas as the model produces them.

        Implementations translate the shared `messages` into their SDK's format
        and yield plain text chunks. They must NOT yield provider-specific
        objects — only str deltas — so callers stay provider-agnostic.

        (This is an async generator in subclasses; declared here as an abstract
        coroutine returning an AsyncIterator so type-checkers are happy.)
        """
        raise NotImplementedError

    async def complete(self, messages: list[Message]) -> str:
        """Return the full answer as one string.

        Default implementation drains `stream()`. Step 2 uses this to verify a
        provider works before SSE exists. Subclasses may override with a native
        non-streaming call if preferred, but they don't have to.
        """
        chunks: list[str] = []
        async for delta in self.stream(messages):
            chunks.append(delta)
        return "".join(chunks)
