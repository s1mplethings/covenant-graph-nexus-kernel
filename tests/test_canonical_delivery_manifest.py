from __future__ import annotations

import json
import pathlib
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import canonical_delivery_manifest
from scripts import canonical_evidence_hash
from scripts import customer_runtime_runner
from scripts import local_packager
from scripts import real_test_execution


def write_real_png(path: pathlib.Path, width: int = 80, height: int = 64) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend(((x * 7 + y) % 255, (x * 3 + y * 5) % 255, (x * 11 + y * 2) % 255))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows)))
        + chunk(b"IEND", b"")
    )


def make_canonical_project(root: pathlib.Path, *, provider_screenshot: bool = False) -> pathlib.Path:
    project = root / "project"
    project.mkdir()
    (project / "index.html").write_text("<main><h1>Canonical package</h1></main>\n", encoding="utf-8")
    (project / "README.md").write_text("# Canonical package\n", encoding="utf-8")
    (project / "DELIVERY_NOTES.md").write_text("# Delivery\n\ndelivery_status: PASS\n", encoding="utf-8")
    if provider_screenshot:
        write_real_png(project / "provider_ui.png")
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

    def test_reserved_extra_fields_cannot_override_canonical_truth(self) -> None:
        attempts = {
            "status": "PASS_WITH_LIMITS",
            "package_sha256": "sha256:" + "0" * 64,
            "candidate_hash": "sha256:" + "1" * 64,
            "package_path": "elsewhere/final_project_bundle.zip",
        }
        for field, value in attempts.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                project = make_canonical_project(pathlib.Path(temp))
                manifest = canonical_delivery_manifest.build_canonical_package(
                    project,
                    extra_fields={field: value, "custom_note": "allowed"},
                )
                self.assertEqual("NEEDS_REWORK", manifest["status"])
                self.assertIn(f"reserved_extra_field:{field}", manifest["failures"])
                self.assertNotEqual(value, manifest[field])
                self.assertEqual("allowed", manifest["custom_note"])

    def test_manifest_and_package_paths_are_bound_to_delivery_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            project = make_canonical_project(root)
            output = root / "external-delivery"
            manifest = canonical_delivery_manifest.build_canonical_package(project, output_dir=output)
            self.assertEqual(
                "PASS",
                canonical_delivery_manifest.inspect_canonical_delivery_manifest(project, manifest)["status"],
            )

            other = root / "other"
            other.mkdir()
            other_package = other / "final_project_bundle.zip"
            other_package.write_bytes(pathlib.Path(manifest["package_path"]).read_bytes())
            changed = dict(manifest)
            changed["package_path"] = str(other_package)
            changed["package_sha256"] = canonical_evidence_hash.sha256_file(other_package)
            changed["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(changed, ("artifact_hash",))
            pathlib.Path(manifest["manifest_path"]).write_text(
                json.dumps(changed, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            inspection = canonical_delivery_manifest.inspect_canonical_delivery_manifest(project, manifest["manifest_path"])
            self.assertEqual("NEEDS_REWORK", inspection["status"])
            self.assertIn("package_manifest_directory_mismatch", inspection["failures"])

            missing_ref = dict(changed)
            missing_ref["manifest_path"] = str(root / "missing" / "delivery_manifest.json")
            inspection = canonical_delivery_manifest.inspect_canonical_delivery_manifest(project, missing_ref)
            self.assertEqual("NEEDS_REWORK", inspection["status"])
            self.assertIn("manifest_path_invalid", inspection["failures"])

    def test_repacked_entry_content_with_old_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_canonical_project(pathlib.Path(temp))
            manifest = canonical_delivery_manifest.build_canonical_package(project)
            package = pathlib.Path(manifest["package_path"])
            entries: dict[str, bytes] = {}
            with zipfile.ZipFile(package, "r") as archive:
                for name in archive.namelist():
                    entries[name] = archive.read(name)
            target = sorted(entries)[0]
            entries[target] += b"changed-entry"
            with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in entries.items():
                    archive.writestr(name, data)
            inspection = canonical_delivery_manifest.inspect_canonical_delivery_manifest(project, manifest)
            self.assertEqual("NEEDS_REWORK", inspection["status"])
            self.assertIn("package_entries_hash_mismatch", inspection["failures"])

    def test_evidence_change_during_packaging_removes_pass_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_canonical_project(pathlib.Path(temp))
            original = canonical_delivery_manifest.inspect_zip_entries
            changed = False

            def inspect_and_mutate(path: pathlib.Path) -> dict:
                nonlocal changed
                result = original(path)
                if not changed and pathlib.Path(path).suffix == ".tmp":
                    changed = True
                    evidence_path = project / "customer_runtime.json"
                    evidence_path.write_bytes(evidence_path.read_bytes() + b" ")
                return result

            with mock.patch.object(canonical_delivery_manifest, "inspect_zip_entries", side_effect=inspect_and_mutate):
                manifest = canonical_delivery_manifest.build_canonical_package(project)
            self.assertEqual("NEEDS_REWORK", manifest["status"])
            self.assertIn("evidence_changed_during_packaging", manifest["failures"])
            self.assertFalse((project / "final_project_bundle.zip").exists())

    def test_nonvisual_project_without_preview_remains_canonical_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_canonical_project(pathlib.Path(temp))
            manifest = local_packager.package_project(
                project,
                startup_command="python -m http.server 8000",
                visual_required=False,
                media_required=False,
            )
            self.assertFalse(manifest["quality_evidence"]["preview_evidence_found"])
            self.assertFalse(any("未找到预览证据" in item for item in manifest["known_limits"]))
            self.assertEqual("PASS", manifest["status"], manifest)
            self.assertEqual(
                "PASS",
                canonical_delivery_manifest.inspect_canonical_delivery_manifest(project, manifest)["status"],
            )

    def test_manifest_cannot_reference_first_attempt_test_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_canonical_project(pathlib.Path(temp))
            manifest = canonical_delivery_manifest.build_canonical_package(project)
            first_attempt = project / "first_attempt_test_execution.json"
            first_attempt.write_bytes((project / "test_execution.json").read_bytes())
            changed = dict(manifest)
            changed["test_execution_ref"] = str(first_attempt.resolve())
            changed["test_execution_hash"] = canonical_evidence_hash.sha256_file(first_attempt)
            changed["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(changed, ("artifact_hash",))
            pathlib.Path(manifest["manifest_path"]).write_text(
                json.dumps(changed, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            inspection = canonical_delivery_manifest.inspect_canonical_delivery_manifest(
                project,
                manifest["manifest_path"],
            )
            self.assertEqual("NEEDS_REWORK", inspection["status"])
            self.assertIn("test_evidence_ref", inspection["failures"])

    def test_incidental_provider_screenshot_does_not_require_visual_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_canonical_project(pathlib.Path(temp), provider_screenshot=True)
            manifest = local_packager.package_project(
                project,
                screenshot_path=project / "provider_ui.png",
                visual_required=False,
                media_required=False,
            )
            self.assertEqual("PASS", manifest["status"], manifest)
            self.assertEqual("", manifest["visual_evidence_ref"])
            self.assertEqual("", manifest["visual_evidence_hash"])
            self.assertEqual(
                "PASS",
                canonical_delivery_manifest.inspect_canonical_delivery_manifest(
                    project,
                    manifest,
                    visual_required=False,
                )["status"],
            )


if __name__ == "__main__":
    unittest.main()
