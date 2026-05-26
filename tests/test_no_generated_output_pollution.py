from __future__ import annotations

import unittest

from tests.helpers import ROOT


class NoGeneratedOutputPollutionTest(unittest.TestCase):
    def test_no_generated_outputs_or_archives_in_repo(self) -> None:
        bad = []
        for path in ROOT.rglob("*"):
            rel = path.relative_to(ROOT).as_posix()
            if ".git/" in rel or rel.startswith(".git/") or "__pycache__" in rel:
                continue
            if any(part in rel.split("/") for part in ("final_output", "project_output", "generated_outputs", "generated")):
                bad.append(rel)
            if path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".zip"}:
                bad.append(rel)
        self.assertEqual([], bad)


if __name__ == "__main__":
    unittest.main()
