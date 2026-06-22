from pathlib import Path

import unittest

from scribe.config import normalize_command
from scribe.exporter import should_ignore


class ExporterTests(unittest.TestCase):
    def test_normalize_command_collapses_whitespace_and_case(self) -> None:
        self.assertEqual(normalize_command("  CLEAR   SCREEN  "), "clear screen")

    def test_should_ignore_uses_normalized_commands(self) -> None:
        ignored = {normalize_command("CLEAR SCREEN")}
        self.assertTrue(should_ignore(" clear   screen ", ignored))


if __name__ == "__main__":
    unittest.main()
