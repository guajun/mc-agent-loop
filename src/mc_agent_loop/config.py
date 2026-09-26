"""Tunables for the agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field

#: Harness-neutral chat prefixes that address the agent by default.
DEFAULT_TRIGGERS: tuple[str, ...] = ("@agent",)

DEFAULT_SYSTEM_PROMPT = (
    "You are an assistant attached to a Minecraft client through a bridge. "
    "Your replies are posted to in-game chat, so keep them short, plain, and "
    "free of markdown. If you need game data, ask for it instead of guessing."
)


@dataclass
class LoopConfig:
    api_host: str = "127.0.0.1"
    api_port: int = 8765

    #: Case-insensitive prefixes that address the agent in chat.
    triggers: tuple[str, ...] = DEFAULT_TRIGGERS
    #: Never answer these senders (useful for other bots).
    ignore_senders: tuple[str, ...] = ()
    #: The agent's own player name, if the bridge cannot report it yet.
    self_name: str = ""

    #: "chat" posts a chat message; "command" runs reply_command with {json}.
    reply_mode: str = "chat"
    reply_command: str = "tellraw @a {json}"
    chunk_size: int = 220
    chunk_delay: float = 0.6
    max_reply_chars: int = 900

    #: Ignore chat that is older than this, so a backlog does not get replayed.
    max_age_seconds: float = 120.0
    #: Minimum seconds between two replies to the same sender.
    cooldown_seconds: float = 3.0
    #: Minimum seconds between any two replies.
    min_reply_interval: float = 0.5
    #: How many past messages to hand to the backend.
    history_size: int = 12
    backend_timeout: float = 300.0

    #: Extra event categories to subscribe to beyond "chat".
    extra_events: tuple[str, ...] = ()
    #: Event queue depth before new events are dropped.
    queue_size: int = 256

    system_prompt: str = field(default=DEFAULT_SYSTEM_PROMPT)
