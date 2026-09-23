"""Hermes backend (Nous Research hermes-agent), via its OpenAI-compatible API.

Talks to a Hermes API server with the standard library only, so the loop has no
hard dependency on an SDK. Point ``base_url`` at whatever the server listens on
and set the model name your Hermes build serves.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request

from .base import Backend, BackendError, ChatRequest


class HermesBackend(Backend):
    name = "hermes"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 300.0,
        temperature: float = 0.6,
        max_tokens: int = 500,
    ) -> None:
        self.base_url = (base_url or os.environ.get("HERMES_API_BASE") or "http://127.0.0.1:8642").rstrip("/")
        self.model = model or os.environ.get("HERMES_MODEL") or "hermes-agent"
        self.api_key = api_key if api_key is not None else os.environ.get("HERMES_API_KEY", "")
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

    def build_payload(self, request: ChatRequest) -> dict:
        messages: list[dict[str, str]] = []
        system = request.system or ""
        if system:
            messages.append({"role": "system", "content": system})
        for message in request.history:
            messages.append({"role": message.role, "content": message.content})
        spoken = request.text or request.raw_text
        if request.sender:
            messages.append({"role": "user", "content": f"{request.sender}: {spoken}"})
        else:
            messages.append({"role": "user", "content": spoken})
        return {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }

    def parse_reply(self, payload: dict) -> str:
        choices = payload.get("choices") or []
        if not choices:
            raise BackendError(f"hermes returned no choices: {payload!r}")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):  # some builds return content parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not content:
            raise BackendError(f"hermes returned an empty reply: {payload!r}")
        return str(content)

    def _post(self, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key or 'none'}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")[:500]
            raise BackendError(f"hermes HTTP {error.code}: {body}") from error
        except urllib.error.URLError as error:
            raise BackendError(
                f"cannot reach hermes at {self.base_url}: {error.reason}. "
                "Is the API server enabled and running?"
            ) from error
        except json.JSONDecodeError as error:
            raise BackendError(f"hermes sent invalid JSON: {error}") from error

    async def complete(self, request: ChatRequest) -> str:
        payload = self.build_payload(request)
        # urllib is blocking; keep the loop responsive.
        response = await asyncio.to_thread(self._post, payload)
        return self.parse_reply(response)
