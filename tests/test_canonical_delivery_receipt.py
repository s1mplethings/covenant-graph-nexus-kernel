from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.canonical_delivery_receipt as receipt
import scripts.canonical_evidence_hash as evidence_hash
import scripts.telegram_live_bridge as bridge
import scripts.production_candidate_provenance as production_candidate_provenance
from tests.test_telegram_public_delivery_gate import (
    FakeTelegramClient,
    make_deliverable_project,
    make_media_project_without_browser_evidence,
    requirement_session,
)


@pytest.fixture(autouse=True)
def _allow_receipt_test_production_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
):
    temporary_root = pathlib.Path(tempfile.gettempdir()).resolve()
    monkeypatch.setattr(
        production_candidate_provenance,
        "PRODUCTION_CANDIDATE_ROOT",
        temporary_root,
    )
    monkeypatch.setattr(
        bridge.production_candidate_provenance,
        "PRODUCTION_CANDIDATE_ROOT",
        temporary_root,
    )
    monkeypatch.setattr(bridge, "DEFAULT_MEMORY_DIR", tmp_path / "project_memory")
    monkeypatch.setenv(
        "CGNK_LOCAL_STUDIO_CONVERSATION_ROOT",
        str(tmp_path / "conversations"),
    )


class CanonicalDeliveryReceiptTests(unittest.TestCase):
    @staticmethod
    def pass_final_gate(project: pathlib.Path, manifest: dict, session: dict) -> dict:
        gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")
        gate.update({"verdict": "PASS_FINAL", "status": "PASS_FINAL", "delivery_allowed": True, "is_final": True})
        return gate

    def test_nonvisual_final_package_has_canonical_receipt_before_delivered(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            sessions = root / "sessions"
            project, manifest = make_media_project_without_browser_evidence(root, media="none")
            session = requirement_session("receipt-package", "交付最终项目包")
            session["whiteboard"]["project_summary"] = "本地可运行的项目助手"
            session["whiteboard"]["acceptance_criteria"] = ["NO TEST EXECUTED 不能公开交付"]
            session["active_run"] = {"id": "run-package", "status": "running", "created_at": bridge.now()}
            session["generation"] = {"status": "running"}
            bridge.save_session(sessions, session)
            gate = self.pass_final_gate(project, manifest, session)
            with mock.patch.object(bridge, "evaluate_public_delivery_gate", return_value=gate):
                sent = bridge.send_delivery_from_manifest(
                    FakeTelegramClient(), "receipt-package", sessions, session, manifest
                )
            inspection = receipt.inspect_canonical_delivery_receipt(
                project,
                expected_chat_id="receipt-package",
                expected_requirements=bridge.infer_public_delivery_requirements(session, manifest["startup_command"]),
                expected_attachment_refs={item["kind"]: item["path"] for item in sent},
            )
            saved = bridge.load_session(sessions, "receipt-package")

            self.assertEqual("PASS", inspection["status"], inspection)
            self.assertEqual(["package"], inspection["receipt"]["required_attachment_kinds"])
            self.assertEqual(["package"], inspection["receipt"]["sent_attachment_kinds"])
            self.assertEqual("delivered", saved["generation"]["status"])
            self.assertEqual(["package"], [item["kind"] for item in sent])

    def test_real_browser_visual_package_and_screenshot_receipts_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            sessions = root / "sessions"
            project, manifest = make_deliverable_project(root)
            session = requirement_session("receipt-visual", "交付最终项目包和真实界面截图")
            session["active_run"] = {"id": "run-visual", "status": "running", "created_at": bridge.now()}
            session["generation"] = {"status": "running"}
            bridge.save_session(sessions, session)
            gate = self.pass_final_gate(project, manifest, session)
            with mock.patch.object(bridge, "evaluate_public_delivery_gate", return_value=gate):
                bridge.send_delivery_from_manifest(FakeTelegramClient(), "receipt-visual", sessions, session, manifest)
            requirements = bridge.infer_public_delivery_requirements(session, manifest["startup_command"])
            inspection = receipt.inspect_canonical_delivery_receipt(
                project, expected_chat_id="receipt-visual", expected_requirements=requirements,
                expected_attachment_refs={item["kind"]: item["local_ref"] for item in json.loads((project / receipt.RECEIPT_NAME).read_text(encoding="utf-8"))["telegram_receipts"]},
            )

            self.assertEqual("PASS", inspection["status"], inspection)
            self.assertEqual(["package", "screenshot"], inspection["receipt"]["required_attachment_kinds"])
            self.assertEqual(["package", "screenshot"], inspection["receipt"]["sent_attachment_kinds"])
            self.assertTrue(all(item["telegram_file_id"] for item in inspection["receipt"]["telegram_receipts"]))
            self.assertEqual("delivered", bridge.load_session(sessions, "receipt-visual")["generation"]["status"])

    def test_tampering_and_duplicate_message_identity_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            sessions = root / "sessions"
            project, manifest = make_deliverable_project(root)
            session = requirement_session("receipt-tamper", "交付最终项目包和真实界面截图")
            session["active_run"] = {"id": "run-tamper", "status": "running", "created_at": bridge.now()}
            session["generation"] = {"status": "running"}
            bridge.save_session(sessions, session)
            gate = self.pass_final_gate(project, manifest, session)
            with mock.patch.object(bridge, "evaluate_public_delivery_gate", return_value=gate):
                bridge.send_delivery_from_manifest(FakeTelegramClient(), "receipt-tamper", sessions, session, manifest)
            path = project / receipt.RECEIPT_NAME
            document = json.loads(path.read_text(encoding="utf-8"))
            document["telegram_receipts"][1]["telegram_message_id"] = document["telegram_receipts"][0]["telegram_message_id"]
            document["artifact_hash"] = bridge.canonical_evidence_hash.canonical_json_hash(document, ("artifact_hash",))
            path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

            inspection = receipt.inspect_canonical_delivery_receipt(
                project,
                expected_chat_id="receipt-tamper",
                expected_requirements=bridge.infer_public_delivery_requirements(session, manifest["startup_command"]),
                expected_attachment_refs={item["kind"]: item["local_ref"] for item in document["telegram_receipts"]},
            )
            self.assertEqual("NEEDS_REWORK", inspection["status"])
            self.assertIn("duplicate_telegram_message_id", inspection["failures"])

    def test_only_root_authoritative_receipt_is_outside_candidate_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = pathlib.Path(temp)
            (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
            baseline = evidence_hash.candidate_source_hash(project)
            (project / receipt.RECEIPT_NAME).write_text("{}\n", encoding="utf-8")
            self.assertEqual(baseline, evidence_hash.candidate_source_hash(project))
            nested = project / "product" / receipt.RECEIPT_NAME
            nested.parent.mkdir()
            nested.write_text("{}\n", encoding="utf-8")
            self.assertNotEqual(baseline, evidence_hash.candidate_source_hash(project))


if __name__ == "__main__":
    unittest.main()
