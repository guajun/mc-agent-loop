from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from mc_agent_loop.cli import build_parser, load_env_file


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
