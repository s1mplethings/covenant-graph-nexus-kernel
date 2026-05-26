from __future__ import annotations

import tempfile
import unittest

from tests.helpers import ROOT
from cgnk_core import ContractRegistry
from cgnk_core.schema_loader import load_json
from cgnk_ctcp.migration import check_migration_spec, write_reports


class CtcpMigrationSpecTest(unittest.TestCase):
    def test_migration_report_maps_selected_and_rejected(self) -> None:
        registry = ContractRegistry(ROOT, validate_schema=False)
        spec = load_json(ROOT / "examples" / "migrations" / "project_generation.migration.json")
        report = check_migration_spec(spec, registry)
        self.assertTrue(report["ok"], report["diagnostics"])
        self.assertIn("project_generation_pipeline", report["selected"])
        self.assertIn("old_progress_fallback", report["rejected"])
        with tempfile.TemporaryDirectory() as td:
            json_path, md_path = write_reports(report, ROOT / td if False else __import__("pathlib").Path(td))
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())


if __name__ == "__main__":
    unittest.main()
