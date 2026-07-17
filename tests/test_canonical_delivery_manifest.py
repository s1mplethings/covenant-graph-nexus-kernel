from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import canonical_delivery_manifest
from scripts import canonical_evidence_hash
from scripts import customer_runtime_runner
from scripts import real_test_execution


def make_canonical_project(root: pathlib.Path) -> pathlib.Path:
    project = root / "project"
    project.mkdir()
    (project / "index.html").write_text("<main><h1>Canonical package</h1></main>\n", encoding="utf-8")
    (project / "README.md").write_text("# Canonical package\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    candidate_hash = canonical_evidence_hash.candidate_source_hash(project)
    run_id = "run-canonical-package"
    candidate_id = "candidate-canonical-package"
    commit_sha = "commit-canonical-package"
    test_result = real_test_execution.run_tests(
        project,
        run_id=run_id,
        candidate_id=candidate_id,
        candidate_hash=candidate_hash,
        commit_sha=commit_sha,
    )
    if test_result["status"] != "PASS":
        raise AssertionError(test_result)
    runtime_result = customer_runtime_runner.run(
        project,
        run_id=run_id,
        candidate_id=candidate_id,
        candidate_hash=candidate_hash,
        commit_sha=commit_sha,
    )
    if runtime_result["status"] != "PASS":
        raise AssertionError(runtime_result)
    return project


class CanonicalDeliveryManifestTests(unittest.TestCase):
    def test_producer_and_inspector_recompute_all_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_canonical_project(pathlib.Path(temp))
            manifest = canonical_delivery_manifest.build_canonical_package(project)
            inspection = canonical_delivery_manifest.inspect_canonical_delivery_manifest(project, manifest)
            self.assertEqual("PASS", manifest["status"], manifest)
            self.assertEqual("PASS", inspection["status"], inspection)
            self.assertEqual(manifest["candidate_hash"], manifest["source_tree_hash"])
            self.assertEqual(canonical_evidence_hash.sha256_file(manifest["package_path"]), manifest["package_sha256"])
            self.assertEqual(
                canonical_delivery_manifest.inspect_zip_entries(manifest["package_path"])["package_entries_hash"],
                manifest["package_entries_hash"],
            )
            self.assertEqual(
                canonical_evidence_hash.canonical_json_hash(manifest, ("artifact_hash",)),
                manifest["artifact_hash"],
            )

    def test_zip_bytes_and_source_tamper_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_canonical_project(pathlib.Path(temp))
            manifest = canonical_delivery_manifest.build_canonical_package(project)
            package = pathlib.Path(manifest["package_path"])
            package.write_bytes(package.read_bytes() + b"tamper")
            inspection = canonical_delivery_manifest.inspect_canonical_delivery_manifest(project, manifest)
            self.assertEqual("NEEDS_REWORK", inspection["status"])
            self.assertIn("package_sha256_mismatch", inspection["failures"])

            manifest = canonical_delivery_manifest.build_canonical_package(project)
            (project / "index.html").write_text("<main>changed</main>\n", encoding="utf-8")
            inspection = canonical_delivery_manifest.inspect_canonical_delivery_manifest(project, manifest)
            self.assertEqual("NEEDS_REWORK", inspection["status"])
            self.assertIn("source_tree_hash_mismatch", inspection["failures"])

    def test_each_declared_hash_tamper_is_recomputed(self) -> None:
        fields = {
            "source_tree_hash": "source_tree_hash_mismatch",
            "package_sha256": "package_sha256_mismatch",
            "package_entries_hash": "package_entries_hash_mismatch",
            "artifact_hash": "artifact_hash_mismatch",
            "test_execution_hash": "test_evidence_hash",
            "customer_runtime_hash": "runtime_evidence_hash",
        }
        for field, expected in fields.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                project = make_canonical_project(pathlib.Path(temp))
                manifest = canonical_delivery_manifest.build_canonical_package(project)
                manifest[field] = "sha256:" + "0" * 64
                if field != "artifact_hash":
                    manifest["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(manifest, ("artifact_hash",))
                pathlib.Path(manifest["manifest_path"]).write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                inspection = canonical_delivery_manifest.inspect_canonical_delivery_manifest(project)
                self.assertEqual("NEEDS_REWORK", inspection["status"])
                self.assertIn(expected, inspection["failures"])

    def test_source_change_during_packaging_cleans_final_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_canonical_project(pathlib.Path(temp))
            original = canonical_delivery_manifest.inspect_zip_entries
            changed = False

            def inspect_and_mutate(path: pathlib.Path) -> dict:
                nonlocal changed
                result = original(path)
                if not changed and pathlib.Path(path).suffix == ".tmp":
                    changed = True
                    (project / "index.html").write_text("<main>mutated during package</main>\n", encoding="utf-8")
                return result

            with mock.patch.object(canonical_delivery_manifest, "inspect_zip_entries", side_effect=inspect_and_mutate):
                manifest = canonical_delivery_manifest.build_canonical_package(project)
            self.assertEqual("NEEDS_REWORK", manifest["status"])
            self.assertIn("source_changed_during_packaging", manifest["failures"])
            self.assertFalse((project / "final_project_bundle.zip").exists())

    def test_nested_old_delivery_bundle_blocks_but_product_zip_is_included(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_canonical_project(pathlib.Path(temp))
            (project / "assets").mkdir()
            (project / "assets" / "product_input.zip").write_bytes(b"product zip")
            (project / "legacy").mkdir()
            (project / "legacy" / "final_project_bundle.old.zip").write_bytes(b"old delivery")
            manifest = canonical_delivery_manifest.build_canonical_package(project)
            self.assertEqual("NEEDS_REWORK", manifest["status"])
            self.assertTrue(any(item.startswith("nested_delivery_bundle:") for item in manifest["failures"]))
            entries, _ = canonical_delivery_manifest.build_inclusion_manifest(project)
            self.assertIn("assets/product_input.zip", {item["relative_path"] for item in entries})

    def test_malicious_duplicate_and_corrupt_zip_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            malicious = root / "malicious.zip"
            with zipfile.ZipFile(malicious, "w") as archive:
                archive.writestr("../escape.txt", b"x")
                archive.writestr("/absolute.txt", b"x")
                archive.writestr("same.txt", b"one")
                archive.writestr("same.txt", b"two")
            result = canonical_delivery_manifest.inspect_zip_entries(malicious)
            self.assertEqual("NEEDS_REWORK", result["status"])
            self.assertTrue(any(item.startswith("archive_path_traversal:") for item in result["failures"]))
            self.assertTrue(any(item.startswith("absolute_archive_member:") for item in result["failures"]))
            self.assertTrue(any(item.startswith("duplicate_archive_member:") for item in result["failures"]))
            corrupt = root / "corrupt.zip"
            corrupt.write_bytes(b"not a zip")
            self.assertEqual("NEEDS_REWORK", canonical_delivery_manifest.inspect_zip_entries(corrupt)["status"])

    def test_legacy_and_nonfinal_statuses_never_pass_inspector(self) -> None:
        for status in ("ready", "ready_with_warnings", "PASS_WITH_LIMITS", "NEEDS_REWORK"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp:
                project = make_canonical_project(pathlib.Path(temp))
                manifest = canonical_delivery_manifest.build_canonical_package(project)
                manifest["status"] = status
                manifest["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(manifest, ("artifact_hash",))
                pathlib.Path(manifest["manifest_path"]).write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                inspection = canonical_delivery_manifest.inspect_canonical_delivery_manifest(project)
                self.assertEqual("NEEDS_REWORK", inspection["status"])
                self.assertIn(f"manifest_status:{status}", inspection["failures"])


if __name__ == "__main__":
    unittest.main()
