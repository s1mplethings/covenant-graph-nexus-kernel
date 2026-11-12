"""Milestone M11: Media test suite.

Exercises the declared public contract for media.import, media.get, media.list,
signature validation rules, integrity checks (VALID/BROKEN), and integration
with M6 approval / M7 publication workflows that must block broken media.
"""

import hashlib
import json
import os
import shutil
import tempfile
import unittest

from milestones.milestone_20f2614f6ae8403d4a4e.api import handle as m1_handle
from milestones.milestone_dbb8341c8910593063a8.api import handle as m11_handle


# Minimal but signature-valid byte fixtures. The module is required to recognize
# at least PNG/JPEG signatures for images and MP4/WebM signatures for videos.
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    + b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    + b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    + b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c"
    + b"\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c"
    + b"\x1c$.\'\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c"
    + b"\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\xff\xd9"
)

MP4_BYTES = (
    b"\x00\x00\x00 ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
    + b"\x00\x00\x00\x08free\x00\x00\x00\x00"
)

WEBM_BYTES = (
    b"\x1a\x45\xdf\xa3\x01\x00\x00\x00\x00\x00\x00\x1f\x42\x86\x81\x01"
    + b"\x42\xf7\x81\x01\x42\xf2\x81\x04\x42\xf3\x81\x08\x42\x82\x84\x57\x45\x42\x4d\x4c\x42\x87"
)

GARBAGE_BYTES = b"this is not a valid image or video payload at all"


def _write_file(path, data):
    with open(path, "wb") as f:
        f.write(data)
    return path


class M11MediaTest(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp(prefix="m11_media_")
        self.src_dir = tempfile.mkdtemp(prefix="m11_src_")
        # Create an isolated project via M1 so media ops have a valid project_id.
        proj = m1_handle(self.data_dir, {"op": "project.create", "name": "p1"})
        self.project_id = proj["id"]
        other = m1_handle(self.data_dir, {"op": "project.create", "name": "p2"})
        self.other_project_id = other["id"]

    def tearDown(self):
        shutil.rmtree(self.data_dir, ignore_errors=True)
        shutil.rmtree(self.src_dir, ignore_errors=True)

    # ------------------------------------------------------------------ helpers
    def _import(self, path, kind, project_id=None):
        return m11_handle(self.data_dir, {
            "op": "media.import",
            "project_id": project_id or self.project_id,
            "path": path,
            "kind": kind,
        })

    def _get(self, media_id, project_id=None):
        return m11_handle(self.data_dir, {
            "op": "media.get",
            "project_id": project_id or self.project_id,
            "media_id": media_id,
        })

    def _list(self, project_id=None):
        return m11_handle(self.data_dir, {
            "op": "media.list",
            "project_id": project_id or self.project_id,
        })

    def _stored_path(self, record):
        return os.path.join(self.data_dir, record["path"])

    # ------------------------------------------------------------- import tests
    def test_import_valid_png(self):
        src = _write_file(os.path.join(self.src_dir, "a.png"), PNG_BYTES)
        rec = self._import(src, "image")
        self.assertEqual(rec["kind"], "image")
        self.assertEqual(rec["status"], "VALID")
        self.assertEqual(rec["project_id"], self.project_id)
        self.assertTrue(isinstance(rec["id"], str) and rec["id"])
        self.assertEqual(
            rec["sha256"], hashlib.sha256(PNG_BYTES).hexdigest()
        )
        # Bytes were actually copied into project-owned storage.
        stored = self._stored_path(rec)
        self.assertTrue(os.path.exists(stored))
        with open(stored, "rb") as f:
            self.assertEqual(f.read(), PNG_BYTES)

    def test_import_valid_jpeg(self):
        src = _write_file(os.path.join(self.src_dir, "b.jpg"), JPEG_BYTES)
        rec = self._import(src, "image")
        self.assertEqual(rec["status"], "VALID")
        self.assertEqual(rec["kind"], "image")

    def test_import_valid_mp4(self):
        src = _write_file(os.path.join(self.src_dir, "c.mp4"), MP4_BYTES)
        rec = self._import(src, "video")
        self.assertEqual(rec["status"], "VALID")
        self.assertEqual(rec["kind"], "video")

    def test_import_valid_webm(self):
        src = _write_file(os.path.join(self.src_dir, "d.webm"), WEBM_BYTES)
        rec = self._import(src, "video")
        self.assertEqual(rec["status"], "VALID")
        self.assertEqual(rec["kind"], "video")

    def test_import_empty_file_rejected(self):
        src = _write_file(os.path.join(self.src_dir, "empty.png"), b"")
        with self.assertRaises(ValueError):
            self._import(src, "image")

    def test_import_signature_mismatch_rejected(self):
        # PNG bytes declared as video -> mismatch.
        src = _write_file(os.path.join(self.src_dir, "mismatch.bin"), PNG_BYTES)
        with self.assertRaises(ValueError):
            self._import(src, "video")
        # Video bytes declared as image -> mismatch.
        src2 = _write_file(os.path.join(self.src_dir, "mismatch2.bin"), MP4_BYTES)
        with self.assertRaises(ValueError):
            self._import(src2, "image")

    def test_import_garbage_rejected(self):
        src = _write_file(os.path.join(self.src_dir, "garbage.bin"), GARBAGE_BYTES)
        with self.assertRaises(ValueError):
            self._import(src, "image")
        with self.assertRaises(ValueError):
            self._import(src, "video")

    def test_import_invalid_kind_rejected(self):
        src = _write_file(os.path.join(self.src_dir, "k.png"), PNG_BYTES)
        with self.assertRaises(ValueError):
            self._import(src, "audio")

    def test_import_missing_source_path_rejected(self):
        missing = os.path.join(self.src_dir, "does_not_exist.png")
        with self.assertRaises(ValueError):
            self._import(missing, "image")

    # ---------------------------------------------------------------- get tests
    def test_get_returns_record_and_verifies_integrity(self):
        src = _write_file(os.path.join(self.src_dir, "g.png"), PNG_BYTES)
        rec = self._import(src, "image")
        got = self._get(rec["id"])
        self.assertEqual(got["id"], rec["id"])
        self.assertEqual(got["status"], "VALID")
        self.assertEqual(got["sha256"], rec["sha256"])

    def test_get_marks_broken_when_bytes_modified(self):
        src = _write_file(os.path.join(self.src_dir, "mod.png"), PNG_BYTES)
        rec = self._import(src, "image")
        stored = self._stored_path(rec)
        with open(stored, "wb") as f:
            f.write(b"corrupted content here")
        got = self._get(rec["id"])
        self.assertEqual(got["status"], "BROKEN")

    def test_get_marks_broken_when_bytes_missing(self):
        src = _write_file(os.path.join(self.src_dir, "del.png"), PNG_BYTES)
        rec = self._import(src, "image")
        stored = self._stored_path(rec)
        os.remove(stored)
        got = self._get(rec["id"])
        self.assertEqual(got["status"], "BROKEN")

    def test_get_unknown_media_id_rejected(self):
        with self.assertRaises(ValueError):
            self._get("no-such-media-id")

    def test_get_cross_project_rejected(self):
        src = _write_file(os.path.join(self.src_dir, "x.png"), PNG_BYTES)
        rec = self._import(src, "image")
        with self.assertRaises(ValueError):
            self._get(rec["id"], project_id=self.other_project_id)

    # --------------------------------------------------------------- list tests
    def test_list_returns_items_with_status(self):
        src1 = _write_file(os.path.join(self.src_dir, "l1.png"), PNG_BYTES)
        src2 = _write_file(os.path.join(self.src_dir, "l2.mp4"), MP4_BYTES)
        r1 = self._import(src1, "image")
        r2 = self._import(src2, "video")
        res = self._list()
        self.assertIn("items", res)
        ids = {i["id"] for i in res["items"]}
        self.assertIn(r1["id"], ids)
        self.assertIn(r2["id"], ids)
        for item in res["items"]:
            self.assertIn(item["status"], ("VALID", "BROKEN"))

    def test_list_reflects_broken_after_modification(self):
        src = _write_file(os.path.join(self.src_dir, "lb.png"), PNG_BYTES)
        rec = self._import(src, "image")
        stored = self._stored_path(rec)
        with open(stored, "wb") as f:
            f.write(b"tampered")
        res = self._list()
        match = [i for i in res["items"] if i["id"] == rec["id"]][0]
        self.assertEqual(match["status"], "BROKEN")

    def test_list_is_project_isolated(self):
        src = _write_file(os.path.join(self.src_dir, "iso.png"), PNG_BYTES)
        self._import(src, "image")
        other_res = self._list(project_id=self.other_project_id)
        self.assertEqual(other_res["items"], [])

    # ------------------------------------------------------- validation/contract
    def test_unknown_op_rejected(self):
        with self.assertRaises(ValueError):
            m11_handle(self.data_dir, {
                "op": "media.delete",
                "project_id": self.project_id,
            })

    def test_missing_op_rejected(self):
        with self.assertRaises(ValueError):
            m11_handle(self.data_dir, {"project_id": self.project_id})

    def test_invalid_data_dir_rejected(self):
        with self.assertRaises(ValueError):
            m11_handle("", {"op": "media.list", "project_id": self.project_id})

    def test_non_dict_request_rejected(self):
        with self.assertRaises(ValueError):
            m11_handle(self.data_dir, "not-a-dict")

    def test_import_requires_existing_project(self):
        src = _write_file(os.path.join(self.src_dir, "np.png"), PNG_BYTES)
        with self.assertRaises(ValueError):
            self._import(src, "image", project_id="nonexistent-project")

    def test_no_success_shaped_error_objects(self):
        # A failed import must raise, never return a dict carrying an error field.
        src = _write_file(os.path.join(self.src_dir, "err.png"), GARBAGE_BYTES)
        try:
            result = self._import(src, "image")
        except ValueError:
            return
        self.fail("expected ValueError, got %r" % (result,))

    # ------------------------------------------------------ persistence/restart
    def test_persistence_survives_process_restart(self):
        src = _write_file(os.path.join(self.src_dir, "persist.png"), PNG_BYTES)
        rec = self._import(src, "image")
        # Simulate a fresh process by re-reading from disk only (new handle call).
        got = m11_handle(self.data_dir, {
            "op": "media.get",
            "project_id": self.project_id,
            "media_id": rec["id"],
        })
        self.assertEqual(got["id"], rec["id"])
        self.assertEqual(got["status"], "VALID")
        self.assertEqual(got["sha256"], rec["sha256"])

    # ------------------------------------------- M6/M7 integration (broken gate)
    def _content_with_media(self, media_ids):
        """Create a DRAFT content record referencing the given media_ids via M5."""
        from milestones.milestone_90b8868c7203e2958397.api import handle as m4_handle
        from milestones.milestone_9165a990eed5b9c8801e.api import handle as m5_handle
        camp = m4_handle(self.data_dir, {
            "op": "campaign.create",
            "project_id": self.project_id,
            "name": "c1",
            "audience": "a",
            "channels": ["web"],
        })
        content = m5_handle(self.data_dir, {
            "op": "content.create",
            "project_id": self.project_id,
            "campaign_id": camp["id"],
            "channel": "web",
            "text": "hello world",
            "claim_ids": [],
            "media_ids": list(media_ids),
        })
        return content["id"]

    def test_m6_approval_blocks_broken_media(self):
        from milestones.milestone_33270fed0c9054f5ae04.api import handle as m6_handle
        src = _write_file(os.path.join(self.src_dir, "appr.png"), PNG_BYTES)
        rec = self._import(src, "image")
        content_id = self._content_with_media([rec["id"]])
        # Move to REVIEW first.
        m6_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": content_id,
        })
        # Break the stored bytes.
        stored = self._stored_path(rec)
        with open(stored, "wb") as f:
            f.write(b"corrupted")
        # Approval must be blocked because referenced media is BROKEN.
        with self.assertRaises(ValueError):
            m6_handle(self.data_dir, {
                "op": "approval.approve",
                "project_id": self.project_id,
                "content_id": content_id,
            })

    def test_m6_approval_allows_valid_media(self):
        from milestones.milestone_33270fed0c9054f5ae04.api import handle as m6_handle
        src = _write_file(os.path.join(self.src_dir, "ok.png"), PNG_BYTES)
        rec = self._import(src, "image")
        content_id = self._content_with_media([rec["id"]])
        m6_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": content_id,
        })
        result = m6_handle(self.data_dir, {
            "op": "approval.approve",
            "project_id": self.project_id,
            "content_id": content_id,
        })
        self.assertEqual(result["status"], "APPROVED")

    def test_m7_publish_blocks_broken_media(self):
        from milestones.milestone_33270fed0c9054f5ae04.api import handle as m6_handle
        from promotion_publish import handle as m7_handle
        src = _write_file(os.path.join(self.src_dir, "pub.png"), PNG_BYTES)
        rec = self._import(src, "image")
        content_id = self._content_with_media([rec["id"]])
        m6_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": content_id,
        })
        m6_handle(self.data_dir, {
            "op": "approval.approve",
            "project_id": self.project_id,
            "content_id": content_id,
        })
        # Break the stored bytes after approval.
        stored = self._stored_path(rec)
        with open(stored, "wb") as f:
            f.write(b"corrupted")
        with self.assertRaises(ValueError):
            m7_handle(self.data_dir, {
                "op": "publish.send",
                "project_id": self.project_id,
                "content_id": content_id,
                "platform_url": "http://localhost:1/publish",
                "idempotency_key": "k1",
            })

    def test_m7_publish_blocks_missing_media(self):
        from milestones.milestone_33270fed0c9054f5ae04.api import handle as m6_handle
        from promotion_publish import handle as m7_handle
        src = _write_file(os.path.join(self.src_dir, "miss.png"), PNG_BYTES)
        rec = self._import(src, "image")
        content_id = self._content_with_media([rec["id"]])
        m6_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": content_id,
        })
        m6_handle(self.data_dir, {
            "op": "approval.approve",
            "project_id": self.project_id,
            "content_id": content_id,
        })
        # Remove the stored bytes entirely.
        stored = self._stored_path(rec)
        os.remove(stored)
        with self.assertRaises(ValueError):
            m7_handle(self.data_dir, {
                "op": "publish.send",
                "project_id": self.project_id,
                "content_id": content_id,
                "platform_url": "http://localhost:1/publish",
                "idempotency_key": "k2",
            })


if __name__ == "__main__":
    unittest.main()
