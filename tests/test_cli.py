from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from mc_agent_loop.cli import _build_config, build_parser, load_env_file, main
from mc_agent_loop.config import DEFAULT_TRIGGERS, ConfigFileError, LoopConfig


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


class ConfigFileTests(unittest.TestCase):
    """The TOML config file entry point for game chat triggers."""

    def setUp(self) -> None:
        self.parser = build_parser()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def config_path(self, text: str) -> str:
        path = Path(self.directory.name) / "mc-agent-loop.toml"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def build(self, *argv: str) -> LoopConfig:
        return _build_config(self.parser.parse_args(["run", *argv]))

    def assert_config_error(self, argv: list[str], *fragments: str) -> str:
        with self.assertRaises(ConfigFileError) as caught:
            self.build(*argv)
        message = str(caught.exception)
        for fragment in fragments:
            self.assertIn(fragment, message)
        return message

    def test_config_file_sets_one_or_more_triggers(self) -> None:
        path = self.config_path('triggers = ["@bot", "!ai"]\n')
        self.assertEqual(self.build("--config", path).triggers, ("@bot", "!ai"))

    def test_config_file_trigger_whitespace_is_trimmed(self) -> None:
        path = self.config_path('triggers = ["  @bot  "]\n')
        self.assertEqual(self.build("--config", path).triggers, ("@bot",))

    def test_repeated_cli_triggers_override_the_config_file(self) -> None:
        path = self.config_path('triggers = ["@file"]\n')
        config = self.build("--config", path, "--trigger", "@cli", "--trigger", "!ai")
        self.assertEqual(config.triggers, ("@cli", "!ai"))

    def test_builtin_default_without_cli_or_config(self) -> None:
        self.assertEqual(self.build().triggers, ("@agent",))
        self.assertEqual(DEFAULT_TRIGGERS, ("@agent",))

    def test_explicit_config_file_is_validated_even_when_cli_triggers_win(self) -> None:
        missing = str(Path(self.directory.name) / "missing.toml")
        self.assert_config_error(
            ["--config", missing, "--trigger", "@cli"],
            missing,
            "cannot read config file",
        )

    def test_missing_config_file_is_an_error(self) -> None:
        missing = str(Path(self.directory.name) / "missing.toml")
        self.assert_config_error(
            ["--config", missing], missing, "cannot read config file"
        )

    def test_unreadable_config_file_is_an_error(self) -> None:
        # A directory can never be read as a file, on any platform.
        self.assert_config_error(
            ["--config", self.directory.name],
            self.directory.name,
            "cannot read config file",
        )

    def test_unparseable_config_file_is_an_error(self) -> None:
        path = self.config_path("triggers = [\n")
        self.assert_config_error(
            ["--config", path], path, "cannot parse config file"
        )

    def test_missing_triggers_key_is_an_error(self) -> None:
        path = self.config_path('other = ["@bot"]\n')
        self.assert_config_error(
            ["--config", path], path, "missing the required 'triggers' key"
        )

    def test_empty_config_file_is_an_error(self) -> None:
        path = self.config_path("")
        self.assert_config_error(["--config", path], path, "'triggers'")

    def test_empty_triggers_list_is_an_error(self) -> None:
        path = self.config_path("triggers = []\n")
        self.assert_config_error(["--config", path], path, "empty list")

    def test_non_list_triggers_is_an_error(self) -> None:
        for text in ('triggers = "@bot"\n', "triggers = 3\n"):
            with self.subTest(text=text):
                path = self.config_path(text)
                self.assert_config_error(
                    ["--config", path], path, "'triggers' must be a list"
                )

    def test_non_string_trigger_element_is_an_error(self) -> None:
        path = self.config_path('triggers = ["@bot", 7]\n')
        self.assert_config_error(["--config", path], path, "'triggers[1]'")

    def test_empty_trigger_element_is_an_error(self) -> None:
        cases = (
            ('triggers = ["@bot", ""]\n', "'triggers[1]'"),
            ('triggers = ["  "]\n', "'triggers[0]'"),
        )
        for text, key in cases:
            with self.subTest(text=text):
                path = self.config_path(text)
                self.assert_config_error(["--config", path], path, key)

    def test_main_reports_a_config_error_and_exits_nonzero(self) -> None:
        missing = str(Path(self.directory.name) / "missing.toml")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(["run", "--config", missing])
        self.assertEqual(code, 1)
        output = stderr.getvalue()
        self.assertIn("error:", output)
        self.assertIn(missing, output)

    def test_config_file_is_documented_in_run_help(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["run", "--help"])
        help_text = output.getvalue()
        self.assertIn("--config", help_text)
        self.assertIn("'triggers'", help_text)
        self.assertIn("built-in @agent", help_text)
