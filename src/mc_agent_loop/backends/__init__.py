"""Backend registry."""

from __future__ import annotations

from typing import Any

from .base import Backend, BackendError, ChatMessage, ChatRequest
from .echo import EchoBackend
from .hermes import HermesBackend

BACKENDS = {
    "echo": EchoBackend,
    "hermes": HermesBackend,
}


def build_backend(name: str, **options: Any) -> Backend:
    try:
        factory = BACKENDS[name]
    except KeyError as error:
        raise ValueError(
            f"unknown backend {name!r}; available: {', '.join(sorted(BACKENDS))}"
        ) from error
    cleaned = {key: value for key, value in options.items() if value is not None}
    return factory(**cleaned)


__all__ = [
    "BACKENDS",
    "Backend",
    "BackendError",
    "ChatMessage",
    "ChatRequest",
    "build_backend",
]
