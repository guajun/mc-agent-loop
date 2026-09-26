from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from mc_agent_loop.cli import _build_config, build_parser, load_env_file, main
from mc_agent_loop.config import DEFAULT_TRIGGERS, LoopConfig


class ParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = build_parser()

    def test_env_file_is_accepted_before_or_after_the_subcommand(self) -> None:
        self.assertEqual(
            self.parser.parse_args(["--env-file", "a.env", "once", "hi"]).env_file, ["a.env"]
        )
        self.assertEqual(
            self.parser.parse_args(["once", "hi", "--env-file", "a.env"]).env_file, ["a.env"]
        )
        self.assertEqual(self.parser.parse_args(["once", "hi"]).env_file, [])

    def test_defaults_and_overrides(self) -> None:
        args = self.parser.parse_args(["run", "--backend", "echo", "--trigger", "@bot"])
        self.assertEqual(args.backend, "echo")
        self.assertEqual(args.trigger, ["@bot"])
        self.assertEqual(args.api_port, 8765)

    def test_default_trigger_is_harness_neutral(self) -> None:
        self.assertEqual(DEFAULT_TRIGGERS, ("@agent",))
        self.assertEqual(LoopConfig().triggers, ("@agent",))
        config = _build_config(self.parser.parse_args(["run"]))
        self.assertEqual(config.triggers, ("@agent",))
        self.assertNotIn("@codex", config.triggers)

    def test_repeated_trigger_flags_replace_the_default(self) -> None:
        args = self.parser.parse_args(["run", "--trigger", "@bot", "--trigger", "!ai"])
        self.assertEqual(args.trigger, ["@bot", "!ai"])
        self.assertEqual(_build_config(args).triggers, ("@bot", "!ai"))

    def test_run_help_names_only_the_default_trigger(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["run", "--help"])
        help_text = output.getvalue()
        self.assertIn("default: @agent", help_text)
        self.assertNotIn("@codex", help_text)

    def test_codex_backend_is_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["run", "--backend", "codex"])

    def test_codex_flags_are_gone(self) -> None:
        for flag in ("--codex-bin", "--codex-cwd", "--codex-arg"):
            with self.subTest(flag=flag):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        self.parser.parse_args(["run", flag, "value"])


class BackendsCommandTests(unittest.TestCase):
    def test_lists_only_supported_backends(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["backends"]), 0)
        listing = output.getvalue()
        self.assertIn("echo", listing)
        self.assertIn("hermes", listing)
        self.assertNotIn("codex", listing)


class EnvFileTests(unittest.TestCase):
    def test_loads_keys_without_overriding_the_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "# comment\nHERMES_MODEL=from-file\nMC_TEST_NEW_KEY=value\nbroken line\n",
                encoding="utf-8",
            )
            os.environ["HERMES_MODEL"] = "from-shell"
            os.environ.pop("MC_TEST_NEW_KEY", None)
            try:
                load_env_file(str(path))
                self.assertEqual(os.environ["HERMES_MODEL"], "from-shell")
                self.assertEqual(os.environ["MC_TEST_NEW_KEY"], "value")
            finally:
                os.environ.pop("MC_TEST_NEW_KEY", None)
                os.environ.pop("HERMES_MODEL", None)

    def test_missing_file_is_ignored(self) -> None:
        load_env_file(str(Path(tempfile.gettempdir()) / "definitely-missing.env"))
