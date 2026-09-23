"""A stand-in for the bridge daemon: a local API server with recorded calls."""

from __future__ import annotations

import time
from typing import Any

from mc_agent_bridge.local_api import LocalApiServer


class FakeBridge:
    def __init__(self, name: str = "Bot") -> None:
        self.name = name
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.server = LocalApiServer("127.0.0.1", 0, self._handle)

    async def start(self) -> int:
        await self.server.start()
        return self.server.port

    async def stop(self) -> None:
        await self.server.stop()

    async def _handle(self, method: str, params: dict[str, Any]) -> Any:
        self.calls.append((method, params))
        if method == "state":
            return {"type": "state", "name": self.name, "inWorld": True}
        if method == "chat":
            return {"type": "chat_ack", "detail": params.get("message")}
        if method == "command":
            return {"type": "cmd_ack", "detail": params.get("command")}
        if method == "events":
            return {"events": [], "next": 1, "dropped": False}
        raise RuntimeError(f"unknown method: {method}")

    def push_chat(self, text: str, sender: str, millis: int | None = None) -> None:
        self.server.broadcast(
            "chat",
            {
                "type": "chat",
                "text": text,
                "sender": f"LiteralComponent{{content='{sender}'}}",
                "millis": millis if millis is not None else int(time.time() * 1000),
            },
        )

    def chats(self) -> list[str]:
        return [params["message"] for method, params in self.calls if method == "chat"]

    def commands(self) -> list[str]:
        return [params["command"] for method, params in self.calls if method == "command"]
