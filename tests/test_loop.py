from __future__ import annotations

import asyncio
import contextlib
import time
import unittest

from mc_agent_bridge.local_api import LocalApiClient

from mc_agent_loop.backends.base import Backend, ChatRequest
from mc_agent_loop.backends.echo import EchoBackend
from mc_agent_loop.config import LoopConfig
from mc_agent_loop.loop import AgentLoop, chunk_text, clean_sender, sanitize_reply

from .fake_bridge import FakeBridge


class RecordingBackend(Backend):
    name = "recording"

    def __init__(self, reply: str = "ack") -> None:
        self.reply = reply
        self.requests: list[ChatRequest] = []

    async def complete(self, request: ChatRequest) -> str:
        self.requests.append(request)
        return self.reply


async def wait_for(predicate, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


class HelperTests(unittest.TestCase):
    def test_clean_sender_extracts_component_content(self) -> None:
        self.assertEqual(clean_sender("LiteralComponent{content='player_one'}"), "player_one")
        self.assertEqual(clean_sender("player_one"), "player_one")
        self.assertEqual(clean_sender(""), "")

    def test_sanitize_reply_is_one_line(self) -> None:
        self.assertEqual(sanitize_reply("a\nb\r\nc"), "a b c")
        self.assertTrue(sanitize_reply("x" * 50, limit=10).endswith("\u2026"))

    def test_chunk_text_prefers_word_boundaries(self) -> None:
        self.assertEqual(chunk_text("", 10), [])
        self.assertEqual(chunk_text("short", 10), ["short"])
        chunks = chunk_text("alpha beta gamma delta", 12)
        self.assertEqual(chunks, ["alpha beta", "gamma delta"])
        self.assertTrue(all(len(chunk) <= 5 for chunk in chunk_text("abcdefghij", 5)))


class LoopTests(unittest.IsolatedAsyncioTestCase):
    def make_config(self, **overrides) -> LoopConfig:
        config = LoopConfig()
        config.cooldown_seconds = 0.0
        config.min_reply_interval = 0.0
        config.chunk_delay = 0.0
        for key, value in overrides.items():
            setattr(config, key, value)
        return config

    async def asyncSetUp(self) -> None:
        self.bridge = FakeBridge()
        port = await self.bridge.start()
        self.port = port
        self.loops: list[AgentLoop] = []

    async def asyncTearDown(self) -> None:
        for loop in reversed(self.loops):
            await loop.stop()
        await self.bridge.stop()

    async def make_loop(self, backend=None, config=None) -> AgentLoop:
        config = config or self.make_config()
        loop = AgentLoop(
            config,
            backend or EchoBackend(),
            LocalApiClient(port=self.port),
            log=lambda _message: None,
        )
        await loop.start(retry=False)
        self.loops.append(loop)
        return loop

    async def test_answers_a_triggered_message(self) -> None:
        loop = await self.make_loop()
        self.bridge.push_chat("@codex what time is it", "player_one")
        await wait_for(lambda: self.bridge.chats())
        self.assertEqual(self.bridge.chats(), ["[echo] player_one: what time is it"])
        self.assertEqual(loop.own_name, "Bot")

    async def test_filters_other_chat(self) -> None:
        loop = await self.make_loop()
        self.bridge.push_chat("just chatting", "player_one")
        self.bridge.push_chat("@codex stale", "player_one", millis=int(time.time() * 1000) - 600_000)
        await asyncio.sleep(0.2)
        self.assertEqual(self.bridge.chats(), [])

    async def test_ignores_its_own_messages(self) -> None:
        loop = await self.make_loop()
        self.bridge.push_chat("@codex hello", "Bot")
        await asyncio.sleep(0.2)
        self.assertEqual(self.bridge.chats(), [])

    async def test_ignored_senders_and_cooldown(self) -> None:
        config = self.make_config(ignore_senders=("spammer",), cooldown_seconds=10.0)
        loop = await self.make_loop(config=config)
        self.bridge.push_chat("@codex hi", "spammer")
        await asyncio.sleep(0.1)
        self.assertEqual(self.bridge.chats(), [])

        self.bridge.push_chat("@codex one", "player_one")
        await wait_for(lambda: self.bridge.chats())
        self.bridge.push_chat("@codex two", "player_one")
        await asyncio.sleep(0.2)
        self.assertEqual(len(self.bridge.chats()), 1)

    async def test_history_is_passed_to_the_backend(self) -> None:
        backend = RecordingBackend(reply="first")
        loop = await self.make_loop(backend=backend)
        self.bridge.push_chat("@agent ping", "player_one")
        await wait_for(lambda: len(backend.requests) == 1)
        self.assertEqual(backend.requests[0].history, ())

        backend.reply = "second"
        self.bridge.push_chat("@agent ping again", "player_one")
        await wait_for(lambda: len(backend.requests) == 2)
        history = backend.requests[1].history
        self.assertEqual([message.role for message in history], ["user", "assistant"])
        self.assertEqual(history[1].content, "first")

    async def test_long_replies_are_chunked(self) -> None:
        backend = RecordingBackend(reply="alpha beta gamma delta epsilon zeta")
        config = self.make_config(chunk_size=22)
        loop = await self.make_loop(backend=backend, config=config)
        self.bridge.push_chat("@agent go", "player_one")
        await wait_for(lambda: len(self.bridge.chats()) >= 2)
        self.assertTrue(all(len(chunk) <= 22 for chunk in self.bridge.chats()))
        self.assertEqual(" ".join(self.bridge.chats()), backend.reply)

    async def test_command_reply_mode(self) -> None:
        backend = RecordingBackend(reply="hello there")
        config = self.make_config(reply_mode="command")
        loop = await self.make_loop(backend=backend, config=config)
        self.bridge.push_chat("@agent go", "player_one")
        await wait_for(lambda: self.bridge.commands())
        self.assertEqual(self.bridge.commands(), ['tellraw @a {"text": "hello there"}'])
        self.assertEqual(self.bridge.chats(), [])

    async def test_backend_failure_keeps_the_loop_alive(self) -> None:
        class Exploding(Backend):
            name = "exploding"

            async def complete(self, request: ChatRequest) -> str:
                raise RuntimeError("boom")

        loop = await self.make_loop(backend=Exploding())
        self.bridge.push_chat("@agent go", "player_one")
        await asyncio.sleep(0.2)
        self.assertEqual(self.bridge.chats(), [])
        self.assertTrue(loop._running)

    async def test_once_answers_without_an_event(self) -> None:
        loop = AgentLoop(
            self.make_config(),
            EchoBackend(),
            LocalApiClient(port=self.port),
            log=lambda _message: None,
        )
        reply = await loop.once("@codex ping")
        self.assertEqual(reply, "[echo]: ping")
        self.assertEqual(self.bridge.chats(), ["[echo]: ping"])

    async def test_submit_drops_when_backlog_is_full(self) -> None:
        config = self.make_config(queue_size=1)
        loop = AgentLoop(config, EchoBackend(), LocalApiClient(port=self.port))
        loop.submit({"text": "one"})
        loop.submit({"text": "two"})
        self.assertEqual(loop._queue.qsize(), 1)
        with contextlib.suppress(asyncio.QueueEmpty):
            while True:
                loop._queue.get_nowait()
