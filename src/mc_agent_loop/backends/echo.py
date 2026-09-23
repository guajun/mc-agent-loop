"""Trivial backend: proves the plumbing without calling a model."""

from __future__ import annotations

from .base import Backend, ChatRequest


class EchoBackend(Backend):
    name = "echo"

    def __init__(self, prefix: str = "[echo]") -> None:
        self.prefix = prefix

    async def complete(self, request: ChatRequest) -> str:
        spoken = request.text or request.raw_text
        who = f" {request.sender}" if request.sender else ""
        return f"{self.prefix}{who}: {spoken}".strip()
