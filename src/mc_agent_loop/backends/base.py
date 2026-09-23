"""The small interface every backend implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class BackendError(RuntimeError):
    """Raised when a backend cannot produce a reply."""


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ChatRequest:
    """One thing somebody said to the agent."""

    #: The prompt, i.e. the chat line with the trigger removed.
    text: str
    #: Raw chat line as it arrived.
    raw_text: str
    #: Display name of whoever said it, best effort.
    sender: str
    #: Past exchanges, oldest first. The current message is *not* included.
    history: tuple[ChatMessage, ...] = field(default_factory=tuple)
    system: str = ""


class Backend(ABC):
    """A reply source: an LLM, a shell command, a script, a stub."""

    name = "backend"

    @abstractmethod
    async def complete(self, request: ChatRequest) -> str:
        """Return the reply text, without any chat framing."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release resources. Default is a no-op."""
        return None
