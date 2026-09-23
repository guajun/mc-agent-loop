"""Optional Codex CLI backend.

Hermes is the primary runtime for this framework; this adapter exists so a Codex
session can be driven from chat as well, by shelling out to the ``codex`` binary.
It is off by default and marked experimental: each reply starts a fresh Codex
process, so it is slower and more expensive than a resident backend.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence

from .base import Backend, BackendError, ChatRequest


class CodexBackend(Backend):
    name = "codex"

    def __init__(
        self,
        executable: str = "codex",
        extra_args: Sequence[str] = ("--skip-git-repo-check",),
        cwd: str | None = None,
        timeout: float = 300.0,
        include_history: int = 4,
    ) -> None:
        self.executable = executable
        self.extra_args = tuple(extra_args)
        self.cwd = cwd or os.getcwd()
        self.timeout = timeout
        self.include_history = include_history

    def build_prompt(self, request: ChatRequest) -> str:
        lines: list[str] = []
        for message in request.history[-self.include_history :]:
            speaker = "player" if message.role == "user" else "you"
            lines.append(f"{speaker}: {message.content}")
        if request.sender:
            lines.append(f"player ({request.sender}): {request.text or request.raw_text}")
        else:
            lines.append(f"player: {request.text or request.raw_text}")
        lines.append("Answer in one short plain-text line; it goes to game chat.")
        return "\n".join(lines)

    async def complete(self, request: ChatRequest) -> str:
        command = [self.executable, "exec", *self.extra_args, self.build_prompt(request)]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self.cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as error:
            raise BackendError(f"cannot find the {self.executable!r} executable") from error
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except (asyncio.TimeoutError, TimeoutError) as error:
            process.kill()
            raise BackendError(f"codex timed out after {self.timeout}s") from error
        if process.returncode != 0:
            raise BackendError(
                f"codex exited with {process.returncode}: {stderr.decode('utf-8', 'replace')[:500]}"
            )
        text = stdout.decode("utf-8", "replace").strip()
        if not text:
            raise BackendError("codex produced no output")
        return text
