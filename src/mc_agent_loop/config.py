"""Tunables for the agent loop."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

#: Harness-neutral chat prefixes that address the agent by default.
DEFAULT_TRIGGERS: tuple[str, ...] = ("@agent",)


class ConfigFileError(ValueError):
    """An explicitly given config file cannot be used.

    Falling back to the built-in triggers here would hide a typo in a
    long-running server setup, so these errors must reach the user.
    """


def load_triggers(path: str) -> tuple[str, ...]:
    """Read the ``triggers`` list from an explicit TOML config file.

    Only that one key is read; this is not a general configuration framework.
    A file that cannot be read or parsed, misses the key, or holds an empty
    list, non-string entries, or empty strings raises :class:`ConfigFileError`
    naming the file and the offending key.
    """
    file = Path(path)
    try:
        raw = file.read_bytes()
    except OSError as error:
        raise ConfigFileError(f"cannot read config file '{path}': {error}") from error
    try:
        document = tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ConfigFileError(
            f"cannot read config file '{path}' as UTF-8: {error}"
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigFileError(f"cannot parse config file '{path}': {error}") from error

    if "triggers" not in document:
        raise ConfigFileError(
            f"config file '{path}' is missing the required 'triggers' key "
            '(expected e.g. triggers = ["@bot"])'
        )
    value = document["triggers"]
    if not isinstance(value, list):
        raise ConfigFileError(
            f"config file '{path}': 'triggers' must be a list of non-empty strings, "
            f"got {type(value).__name__}"
        )
    triggers: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ConfigFileError(
                f"config file '{path}': 'triggers[{index}]' must be a string, "
                f"got {type(item).__name__}"
            )
        trigger = item.strip()
        if not trigger:
            raise ConfigFileError(
                f"config file '{path}': 'triggers[{index}]' is empty; "
                "every trigger needs at least one character"
            )
        triggers.append(trigger)
    if not triggers:
        raise ConfigFileError(
            f"config file '{path}': 'triggers' is an empty list; "
            "list at least one chat prefix"
        )
    return tuple(triggers)


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
