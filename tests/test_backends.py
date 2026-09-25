from __future__ import annotations

import importlib.util
import unittest

from mc_agent_loop.backends import BACKENDS, build_backend
from mc_agent_loop.backends.base import BackendError, ChatMessage, ChatRequest
from mc_agent_loop.backends.echo import EchoBackend
from mc_agent_loop.backends.hermes import HermesBackend


def sample_request(**overrides) -> ChatRequest:
    values = {
        "text": "how fast is it going",
        "raw_text": "@agent how fast is it going",
        "sender": "player_one",
        "history": (ChatMessage("user", "player_one: earlier"), ChatMessage("assistant", "42")),
        "system": "be brief",
    }
    values.update(overrides)
    return ChatRequest(**values)


class RegistryTests(unittest.TestCase):
    def test_known_backends(self) -> None:
        self.assertEqual(sorted(BACKENDS), ["echo", "hermes"])
        self.assertIsInstance(build_backend("echo"), EchoBackend)
        self.assertIsInstance(build_backend("hermes"), HermesBackend)

    def test_codex_backend_is_gone(self) -> None:
        self.assertNotIn("codex", BACKENDS)
        with self.assertRaises(ValueError) as caught:
            build_backend("codex")
        self.assertIn("unknown backend 'codex'", str(caught.exception))
        self.assertIn("echo, hermes", str(caught.exception))
        self.assertIsNone(importlib.util.find_spec("mc_agent_loop.backends.codex"))

    def test_unknown_backend(self) -> None:
        with self.assertRaises(ValueError):
            build_backend("nope")

    def test_none_options_are_dropped(self) -> None:
        backend = build_backend("hermes", base_url=None, model="custom")
        self.assertEqual(backend.model, "custom")


class EchoTests(unittest.IsolatedAsyncioTestCase):
    async def test_echo(self) -> None:
        self.assertEqual(await EchoBackend().complete(sample_request()), "[echo] player_one: how fast is it going")
        self.assertEqual(
            await EchoBackend(prefix=">>").complete(sample_request(sender="")), ">>: how fast is it going"
        )


class HermesTests(unittest.TestCase):
    def test_payload_shape(self) -> None:
        backend = HermesBackend(base_url="http://127.0.0.1:8642/", model="hermes-agent")
        payload = backend.build_payload(sample_request())
        self.assertEqual(backend.base_url, "http://127.0.0.1:8642")
        self.assertEqual(payload["model"], "hermes-agent")
        self.assertFalse(payload["stream"])
        self.assertEqual(
            [message["role"] for message in payload["messages"]],
            ["system", "user", "assistant", "user"],
        )
        self.assertEqual(payload["messages"][-1]["content"], "player_one: how fast is it going")

    def test_payload_without_system_prompt(self) -> None:
        payload = HermesBackend().build_payload(sample_request(system="", history=()))
        self.assertEqual(len(payload["messages"]), 1)

    def test_parse_reply(self) -> None:
        backend = HermesBackend()
        self.assertEqual(
            backend.parse_reply({"choices": [{"message": {"content": "hello"}}]}), "hello"
        )
        self.assertEqual(
            backend.parse_reply(
                {"choices": [{"message": {"content": [{"text": "he"}, {"text": "llo"}]}}]}
            ),
            "hello",
        )
        with self.assertRaises(BackendError):
            backend.parse_reply({"choices": []})
        with self.assertRaises(BackendError):
            backend.parse_reply({"choices": [{"message": {"content": ""}}]})
