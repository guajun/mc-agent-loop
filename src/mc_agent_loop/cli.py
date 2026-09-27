"""``mc-agent-loop`` command line."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .backends import BACKENDS, build_backend
from .config import DEFAULT_SYSTEM_PROMPT, DEFAULT_TRIGGERS, LoopConfig, load_triggers
from .loop import AgentLoop


def load_env_file(path: str) -> None:
    """Read KEY=VALUE lines; variables already set win.

    Keeps the Hermes API key out of shell history and out of the command line:
    ``mc-agent-loop run --env-file F:\\mc-agent\\.env``.
    """
    file = Path(path)
    if not file.exists():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _add_backend_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--backend",
        default="hermes",
        choices=sorted(BACKENDS),
        help="reply source (default: hermes)",
    )
    parser.add_argument("--echo-prefix", default="[echo]", help="echo backend prefix")
    parser.add_argument("--hermes-url", default=None, help="hermes API base URL")
    parser.add_argument("--hermes-model", default=None, help="hermes model name")
    parser.add_argument("--hermes-key", default=None, help="hermes API key")


def _add_config_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8765)
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help=(
            "TOML file with a 'triggers' list of chat prefixes; validated when given, "
            f"--trigger wins over it (default: built-in {' '.join(DEFAULT_TRIGGERS)})"
        ),
    )
    parser.add_argument(
        "--trigger",
        action="append",
        default=[],
        help=(
            "chat prefix that addresses the agent "
            f"(default: {' '.join(DEFAULT_TRIGGERS)}; repeatable, replaces the default)"
        ),
    )
    parser.add_argument("--ignore-sender", action="append", default=[])
    parser.add_argument("--self-name", default="", help="the agent's own player name")
    parser.add_argument("--reply-mode", choices=("chat", "command"), default="chat")
    parser.add_argument(
        "--reply-command",
        default="tellraw @a {json}",
        help="command used when --reply-mode=command; {json} is replaced",
    )
    parser.add_argument("--chunk-size", type=int, default=220)
    parser.add_argument("--chunk-delay", type=float, default=0.6)
    parser.add_argument("--max-reply-chars", type=int, default=900)
    parser.add_argument("--max-age", type=float, default=120.0, help="ignore chat older than this")
    parser.add_argument("--cooldown", type=float, default=3.0, help="per-sender cooldown")
    parser.add_argument("--min-reply-interval", type=float, default=0.5)
    parser.add_argument("--history", type=int, default=12, help="messages of context to keep")
    parser.add_argument("--backend-timeout", type=float, default=300.0)
    parser.add_argument("--queue-size", type=int, default=256)
    parser.add_argument("--system", default=None, help="system prompt")
    parser.add_argument("--system-file", default=None, help="read the system prompt from a file")


def _build_config(args: argparse.Namespace) -> LoopConfig:
    system = args.system
    if args.system_file:
        with open(args.system_file, "r", encoding="utf-8") as handle:
            system = handle.read().strip()
    config = LoopConfig()
    config.api_host = args.api_host
    config.api_port = args.api_port
    if args.config is not None:
        # An explicitly given file is always validated, even when --trigger
        # overrides its values: a broken file must not pass silently.
        config.triggers = load_triggers(args.config)
    if args.trigger:
        config.triggers = tuple(args.trigger)
    config.ignore_senders = tuple(args.ignore_sender)
    config.self_name = args.self_name
    config.reply_mode = args.reply_mode
    config.reply_command = args.reply_command
    config.chunk_size = args.chunk_size
    config.chunk_delay = args.chunk_delay
    config.max_reply_chars = args.max_reply_chars
    config.max_age_seconds = args.max_age
    config.cooldown_seconds = args.cooldown
    config.min_reply_interval = args.min_reply_interval
    config.history_size = args.history
    config.backend_timeout = args.backend_timeout
    config.queue_size = args.queue_size
    config.system_prompt = system or DEFAULT_SYSTEM_PROMPT
    return config


def _build_backend_from_args(args: argparse.Namespace):
    options: dict[str, object] = {}
    if args.backend == "echo":
        options["prefix"] = args.echo_prefix
    elif args.backend == "hermes":
        options.update(
            base_url=args.hermes_url,
            model=args.hermes_model,
            api_key=args.hermes_key,
            timeout=args.backend_timeout,
        )
    return build_backend(args.backend, **options)


def _cmd_run(args: argparse.Namespace) -> int:
    config = _build_config(args)
    loop = AgentLoop(config, _build_backend_from_args(args))
    try:
        asyncio.run(loop.run(retry=not args.no_retry))
    except KeyboardInterrupt:
        print("\n[mc-agent-loop] stopped")
    return 0


def _cmd_once(args: argparse.Namespace) -> int:
    config = _build_config(args)
    loop = AgentLoop(config, _build_backend_from_args(args))
    try:
        reply = asyncio.run(loop.once(args.text, sender=args.sender))
    except OSError as error:
        print(f"error: cannot reach the bridge ({error}). Is `mc-bridge run` up?", file=sys.stderr)
        return 1
    if reply is None:
        print("(no reply: the message did not match a trigger, or it was filtered)")
        return 0
    print(reply)
    return 0


def _cmd_backends(_args: argparse.Namespace) -> int:
    print("available backends:")
    print("  echo    local stub, no model, used by the tests")
    print("  hermes  Nous Research hermes-agent via its OpenAI-compatible API (primary)")
    return 0


def _add_env_option(parser: argparse.ArgumentParser) -> None:
    """Accept --env-file before or after the sub-command, like the bridge CLI."""
    suppress = len(parser.prog.split()) > 1
    parser.add_argument(
        "--env-file",
        action="append",
        default=argparse.SUPPRESS if suppress else [],
        help="file of KEY=VALUE lines to load first (default: ./.env when present)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mc-agent-loop",
        description="Wake on chat, ask a backend, answer in game.",
    )
    _add_env_option(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="stay connected and answer chat")
    _add_env_option(run)
    _add_backend_options(run)
    _add_config_options(run)
    run.add_argument("--no-retry", action="store_true", help="exit instead of waiting for the bridge")
    run.set_defaults(func=_cmd_run)

    once = sub.add_parser("once", help="answer a single prompt and exit")
    _add_env_option(once)
    once.add_argument("text")
    once.add_argument("--sender", default="")
    _add_backend_options(once)
    _add_config_options(once)
    once.set_defaults(func=_cmd_once)

    listing = sub.add_parser("backends", help="list available backends")
    listing.set_defaults(func=_cmd_backends)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for path in args.env_file or [".env"]:
        load_env_file(path)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
