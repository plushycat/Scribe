import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from scribe.search import search_sessions


class SearchTests(unittest.TestCase):
    def test_search_sessions_scans_logs_and_markdown(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "one.log").write_text("select * from employees;\n", encoding="utf-8")
            (path / "two.json").write_text('{"skip": true}', encoding="utf-8")

            matches = search_sessions(path, "EMPLOYEES")

        self.assertEqual(len(matches), 1)
        self.assertIn("one.log:1", matches[0])


if __name__ == "__main__":
    unittest.main()
