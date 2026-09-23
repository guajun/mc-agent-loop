"""The agent loop: wait for somebody to address the agent, then answer.

The loop is the *active* half of the pair. The bridge cannot wake an agent by
itself - a tool call has to come from the agent's side - so this process stays
connected to the bridge's event stream and decides when the backend should
think. It is deliberately small: all game knowledge lives in the backend, all
game access lives in the bridge.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from mc_agent_bridge.local_api import LocalApiClient

from .backends.base import Backend, ChatMessage, ChatRequest
from .config import LoopConfig

_FORMAT_RE = re.compile(r"\u00a7.")
_CONTENT_RE = re.compile(r"content='([^']*)'")
_QUOTED_RE = re.compile(r"['\"]([^'\"]{1,64})['\"]")
_WHITESPACE_RE = re.compile(r"\s+")


def clean_sender(raw: str) -> str:
    """Best-effort display name from whatever the mod handed us.

    The mod stringifies a text component, so the sender may arrive as
    ``LiteralComponent{content='name', ...}`` rather than as ``name``.
    """
    if not raw:
        return ""
    text = _FORMAT_RE.sub("", raw)
    match = _CONTENT_RE.search(text)
    if match:
        return _WHITESPACE_RE.sub(" ", match.group(1)).strip()
    match = _QUOTED_RE.search(text)
    if match:
        return _WHITESPACE_RE.sub(" ", match.group(1)).strip()
    return _WHITESPACE_RE.sub(" ", text).strip()


def sanitize_reply(text: str, limit: int = 900) -> str:
    """Chat is one line long: flatten formatting and clamp the length."""
    flat = _WHITESPACE_RE.sub(" ", (text or "").replace("\r", " ").replace("\n", " ")).strip()
    if len(flat) > limit:
        flat = flat[: max(0, limit - 1)].rstrip() + "\u2026"
    return flat


def chunk_text(text: str, size: int) -> list[str]:
    """Split a reply into chat-sized pieces, preferring whitespace boundaries."""
    text = text.strip()
    if not text:
        return []
    if size <= 0 or len(text) <= size:
        return [text]
    chunks: list[str] = []
    current = ""
    for word in text.split(" "):
        while len(word) > size:  # a single absurdly long token
            if current:
                chunks.append(current)
                current = ""
            chunks.append(word[:size])
            word = word[size:]
        candidate = f"{current} {word}".strip()
        if len(candidate) > size:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


class AgentLoop:
    def __init__(
        self,
        config: LoopConfig,
        backend: Backend,
        client: LocalApiClient | None = None,
        log: Callable[[str], None] = print,
    ) -> None:
        self.config = config
        self.backend = backend
        self.client = client or LocalApiClient(config.api_host, config.api_port)
        self.log = log

        self.own_name = config.self_name
        self.history: deque[ChatMessage] = deque(maxlen=max(0, config.history_size))
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(config.queue_size)
        self._seen: dict[tuple[str, str], float] = {}
        self._last_reply_at = 0.0
        self._last_reply_by_sender: dict[str, float] = {}
        self._worker: asyncio.Task[None] | None = None
        self._pump: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._running = False

    # ------------------------------------------------------------------ lifecycle

    async def start(self, retry: bool = True) -> None:
        await self.client.connect(retry=retry)
        await self.client.call("subscribe", {"events": ["chat", *self.config.extra_events]})
        self.own_name = await self._resolve_own_name() or self.own_name
        self._running = True
        self._stop_event = asyncio.Event()
        self._worker = asyncio.create_task(self._work_loop())
        self._pump = asyncio.create_task(self._pump_loop())
        self.log(
            f"[mc-agent-loop] backend={self.backend.name} triggers={list(self.config.triggers)} "
            f"ownName={self.own_name or 'unknown'}"
        )

    async def stop(self) -> None:
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()
        if self._worker is not None:
            worker, self._worker = self._worker, None
            worker.cancel()
            try:
                await worker
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._pump is not None:
            pump, self._pump = self._pump, None
            pump.cancel()
            try:
                await pump
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self.backend.aclose()
        await self.client.close()

    async def run(self, retry: bool = True) -> None:
        await self.start(retry=retry)
        assert self._stop_event is not None
        try:
            await self._stop_event.wait()
        except asyncio.CancelledError:
            raise
        finally:
            await self.stop()

    async def _pump_loop(self) -> None:
        """Forward bridge events into the work queue until cancelled."""
        queue = await self.client.events()
        while True:
            message = await queue.get()
            event = message.get("event")
            data = message.get("data") or {}
            if event == "chat":
                self.submit(data)
            else:
                self.log(f"[mc-agent-loop] event {event}: {data}")

    # --------------------------------------------------------------------- intake

    def submit(self, data: dict[str, Any]) -> None:
        """Queue a chat event; dropped rather than queued when the agent is behind."""
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            self.log("[mc-agent-loop] chat backlog is full; dropping a message")

    async def _work_loop(self) -> None:
        while True:
            data = await self._queue.get()
            try:
                await self.handle_chat(data)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - never let one message kill the loop
                self.log(f"[mc-agent-loop] failed to handle chat: {error!r}")

    async def handle_chat(self, data: dict[str, Any], origin: str = "chat") -> str | None:
        """Filter, think, reply. Returns the reply that was sent, if any.

        ``origin="manual"`` is used by :meth:`once`: a deliberate single turn
        should not need a chat trigger, a duplicate guard or a cooldown.
        """
        manual = origin == "manual"
        raw = str(data.get("text") or "").strip()
        sender = clean_sender(str(data.get("sender") or ""))
        if not raw:
            return None

        millis = data.get("millis") or data.get("receivedAt")
        if millis:
            age = time.time() - (float(millis) / 1000.0)
            if age > self.config.max_age_seconds:
                self.log(f"[mc-agent-loop] ignoring stale chat ({age:.0f}s old)")
                return None

        if self._is_own(sender):
            return None
        if sender and sender.casefold() in {name.casefold() for name in self.config.ignore_senders}:
            return None

        prompt = self.match_trigger(raw)
        if prompt is None:
            if not manual:
                return None
            prompt = raw

        key = (sender.casefold(), raw)
        now = time.monotonic()
        if not manual:
            if now - self._seen.get(key, 0.0) < 20.0:
                return None
            self._seen[key] = now
            if len(self._seen) > 512:
                cutoff = now - 60.0
                self._seen = {seen: at for seen, at in self._seen.items() if at >= cutoff}
            if not self._cooldown_allows(sender, now):
                self.log(f"[mc-agent-loop] cooling down; skipping {sender or 'unknown'}")
                return None

        request = ChatRequest(
            text=prompt or "(no question, they just addressed you)",
            raw_text=raw,
            sender=sender,
            history=tuple(self.history),
            system=self.config.system_prompt,
        )
        self.log(f"[mc-agent-loop] {sender or 'unknown'}: {request.text}")
        try:
            reply = await asyncio.wait_for(
                self.backend.complete(request), timeout=self.config.backend_timeout
            )
        except (asyncio.TimeoutError, TimeoutError):
            self.log(f"[mc-agent-loop] backend timed out after {self.config.backend_timeout}s")
            return None
        except Exception as error:  # noqa: BLE001 - report it, keep the loop alive
            self.log(f"[mc-agent-loop] backend failed: {error}")
            return None

        reply = sanitize_reply(reply, self.config.max_reply_chars)
        if not reply:
            return None
        await self.send_reply(reply, sender)
        self.history.append(
            ChatMessage("user", f"{sender}: {request.text}" if sender else request.text)
        )
        self.history.append(ChatMessage("assistant", reply))
        return reply

    def match_trigger(self, raw: str) -> str | None:
        """Return the prompt with the trigger removed, or None if not addressed."""
        lowered = raw.casefold()
        for trigger in self.config.triggers:
            index = lowered.find(trigger.casefold())
            if index >= 0:
                return (raw[:index] + raw[index + len(trigger) :]).strip()
        return None

    def _is_own(self, sender: str) -> bool:
        return bool(self.own_name) and sender.casefold() == self.own_name.casefold()

    def _cooldown_allows(self, sender: str, now: float) -> bool:
        if now - self._last_reply_at < self.config.min_reply_interval:
            return False
        last = self._last_reply_by_sender.get(sender.casefold(), 0.0)
        return now - last >= self.config.cooldown_seconds

    # --------------------------------------------------------------------- output

    async def send_reply(self, reply: str, sender: str = "") -> None:
        for index, chunk in enumerate(chunk_text(reply, self.config.chunk_size)):
            if index:
                await asyncio.sleep(self.config.chunk_delay)
            await self._deliver(chunk)
        now = time.monotonic()
        self._last_reply_at = now
        if sender:
            self._last_reply_by_sender[sender.casefold()] = now

    async def _deliver(self, chunk: str) -> None:
        if self.config.reply_mode == "command":
            payload = json.dumps({"text": chunk}, ensure_ascii=False)
            command = self.config.reply_command.replace("{json}", payload)
            await self.client.call("command", {"command": command})
            return
        await self.client.call("chat", {"message": chunk})

    async def _resolve_own_name(self) -> str:
        try:
            state = await self.client.call("state")
        except Exception as error:  # noqa: BLE001 - not being in a world is normal
            self.log(f"[mc-agent-loop] cannot read state yet: {error}")
            return ""
        return str(state.get("name") or "")

    # ------------------------------------------------------------------ one-shots

    async def once(self, text: str, sender: str = "", connect: bool = True) -> str | None:
        """Answer a single prompt without waiting for a chat event.

        Handy for tests, manual pokes, and externally scheduled runs: the agent
        does not have to be resident to be useful.
        """
        if connect:
            await self.start(retry=False)
        try:
            return await self.handle_chat(
                {"text": text, "sender": sender, "millis": int(time.time() * 1000)},
                origin="manual",
            )
        finally:
            if connect:
                await self.stop()
