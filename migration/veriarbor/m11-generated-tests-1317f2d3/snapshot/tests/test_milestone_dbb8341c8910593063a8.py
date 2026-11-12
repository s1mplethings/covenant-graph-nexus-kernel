"""Milestone M11: Media test suite.

Exercises the declared public contract for media.import, media.get, media.list,
validation rules, integrity checks, and integration with M6 approval and M7
publication.
"""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _load_module(name, rel_path):
    path = os.path.join(_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


media = _load_module("m11_media_api", os.path.join("milestones", "milestone_dbb8341c8910593063a8", "api.py"))
m1 = _load_module("m1_project_api", os.path.join("milestones", "milestone_20f2614f6ae8403d4a4e", "api.py"))
m3 = _load_module("m3_claim_api", os.path.join("milestones", "milestone_1369a82cde04a7e5887d", "api.py"))
m4 = _load_module("m4_campaign_api", os.path.join("milestones", "milestone_90b8868c7203e2958397", "api.py"))
m5 = _load_module("m5_content_api", os.path.join("milestones", "milestone_9165a990eed5b9c8801e", "api.py"))
m6 = _load_module("m6_approval_api", os.path.join("milestones", "milestone_33270fed0c9054f5ae04", "api.py"))
m7 = _load_module("m7_publish_api", "promotion_publish.py")


# Minimal but signature-valid byte payloads.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF\x00" + b"\x00" * 32 + b"\xff\xd9"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
WEBM_BYTES = b"\x1a\x45\xdf\xa3" + b"\x00" * 32


class MediaTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = self._tmp.name
        self.src_dir = os.path.join(self.data_dir, "_src")
        os.makedirs(self.src_dir, exist_ok=True)
        self.project_id = m1.handle(self.data_dir, {"op": "project.create", "name": "P"})["id"]

    def tearDown(self):
        self._tmp.cleanup()

    def _write_src(self, name, data):
        path = os.path.join(self.src_dir, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def _import(self, name, data, kind):
        path = self._write_src(name, data)
        return media.handle(self.data_dir, {
            "op": "media.import",
            "project_id": self.project_id,
            "path": path,
            "kind": kind,
        })


class TestMediaImport(MediaTestBase):
    def test_import_png_image(self):
        rec = self._import("a.png", PNG_BYTES, "image")
        self.assertEqual(rec["project_id"], self.project_id)
        self.assertEqual(rec["kind"], "image")
        self.assertEqual(rec["status"], "VALID")
        self.assertEqual(rec["sha256"], hashlib.sha256(PNG_BYTES).hexdigest())
        self.assertIsInstance(rec["id"], str)
        self.assertTrue(rec["id"])
        self.assertIsInstance(rec["path"], str)
        self.assertTrue(rec["path"])

    def test_import_jpeg_image(self):
        rec = self._import("a.jpg", JPEG_BYTES, "image")
        self.assertEqual(rec["kind"], "image")
        self.assertEqual(rec["status"], "VALID")
        self.assertEqual(rec["sha256"], hashlib.sha256(JPEG_BYTES).hexdigest())

    def test_import_mp4_video(self):
        rec = self._import("a.mp4", MP4_BYTES, "video")
        self.assertEqual(rec["kind"], "video")
        self.assertEqual(rec["status"], "VALID")
        self.assertEqual(rec["sha256"], hashlib.sha256(MP4_BYTES).hexdigest())

    def test_import_webm_video(self):
        rec = self._import("a.webm", WEBM_BYTES, "video")
        self.assertEqual(rec["kind"], "video")
        self.assertEqual(rec["status"], "VALID")

    def test_import_copies_bytes_into_storage(self):
        rec = self._import("a.png", PNG_BYTES, "image")
        stored = os.path.join(self.data_dir, rec["path"])
        self.assertTrue(os.path.exists(stored))
        with open(stored, "rb") as f:
            self.assertEqual(f.read(), PNG_BYTES)

    def test_import_rejects_empty_file(self):
        path = self._write_src("empty.png", b"")
        with self.assertRaises(ValueError):
            media.handle(self.data_dir, {
                "op": "media.import",
                "project_id": self.project_id,
                "path": path,
                "kind": "image",
            })

    def test_import_rejects_signature_mismatch(self):
        path = self._write_src("fake.png", b"not an image at all")
        with self.assertRaises(ValueError):
            media.handle(self.data_dir, {
                "op": "media.import",
                "project_id": self.project_id,
                "path": path,
                "kind": "image",
            })

    def test_import_rejects_kind_mismatch(self):
        # PNG bytes declared as video must be rejected.
        path = self._write_src("a.png", PNG_BYTES)
        with self.assertRaises(ValueError):
            media.handle(self.data_dir, {
                "op": "media.import",
                "project_id": self.project_id,
                "path": path,
                "kind": "video",
            })

    def test_import_rejects_invalid_kind(self):
        path = self._write_src("a.png", PNG_BYTES)
        with self.assertRaises(ValueError):
            media.handle(self.data_dir, {
                "op": "media.import",
                "project_id": self.project_id,
                "path": path,
                "kind": "audio",
            })

    def test_import_rejects_missing_path(self):
        with self.assertRaises(ValueError):
            media.handle(self.data_dir, {
                "op": "media.import",
                "project_id": self.project_id,
                "path": os.path.join(self.src_dir, "nope.png"),
                "kind": "image",
            })

    def test_import_rejects_unknown_project(self):
        path = self._write_src("a.png", PNG_BYTES)
        with self.assertRaises(ValueError):
            media.handle(self.data_dir, {
                "op": "media.import",
                "project_id": "does-not-exist",
                "path": path,
                "kind": "image",
            })

    def test_import_rejects_empty_project_id(self):
        path = self._write_src("a.png", PNG_BYTES)
        with self.assertRaises(ValueError):
            media.handle(self.data_dir, {
                "op": "media.import",
                "project_id": "",
                "path": path,
                "kind": "image",
            })


class TestMediaGetAndList(MediaTestBase):
    def test_get_returns_valid_record(self):
        rec = self._import("a.png", PNG_BYTES, "image")
        got = media.handle(self.data_dir, {
            "op": "media.get",
            "project_id": self.project_id,
            "media_id": rec["id"],
        })
        self.assertEqual(got["id"], rec["id"])
        self.assertEqual(got["sha256"], rec["sha256"])
        self.assertEqual(got["status"], "VALID")

    def test_get_unknown_media_raises(self):
        with self.assertRaises(ValueError):
            media.handle(self.data_dir, {
                "op": "media.get",
                "project_id": self.project_id,
                "media_id": "missing",
            })

    def test_get_cross_project_raises(self):
        rec = self._import("a.png", PNG_BYTES, "image")
        other = m1.handle(self.data_dir, {"op": "project.create", "name": "Other"})["id"]
        with self.assertRaises(ValueError):
            media.handle(self.data_dir, {
                "op": "media.get",
                "project_id": other,
                "media_id": rec["id"],
            })

    def test_list_returns_items(self):
        r1 = self._import("a.png", PNG_BYTES, "image")
        r2 = self._import("b.mp4", MP4_BYTES, "video")
        res = media.handle(self.data_dir, {"op": "media.list", "project_id": self.project_id})
        self.assertIn("items", res)
        ids = {item["id"] for item in res["items"]}
        self.assertEqual(ids, {r1["id"], r2["id"]})
        for item in res["items"]:
            self.assertEqual(item["status"], "VALID")

    def test_list_is_project_isolated(self):
        self._import("a.png", PNG_BYTES, "image")
        other = m1.handle(self.data_dir, {"op": "project.create", "name": "Other"})["id"]
        res = media.handle(self.data_dir, {"op": "media.list", "project_id": other})
        self.assertEqual(res["items"], [])

    def test_list_unknown_project_raises(self):
        with self.assertRaises(ValueError):
            media.handle(self.data_dir, {"op": "media.list", "project_id": "nope"})


class TestMediaIntegrity(MediaTestBase):
    def test_get_marks_broken_when_bytes_modified(self):
        rec = self._import("a.png", PNG_BYTES, "image")
        stored = os.path.join(self.data_dir, rec["path"])
        with open(stored, "wb") as f:
            f.write(PNG_BYTES + b"tampered")
        got = media.handle(self.data_dir, {
            "op": "media.get",
            "project_id": self.project_id,
            "media_id": rec["id"],
        })
        self.assertEqual(got["status"], "BROKEN")

    def test_get_marks_broken_when_bytes_missing(self):
        rec = self._import("a.png", PNG_BYTES, "image")
        stored = os.path.join(self.data_dir, rec["path"])
        os.remove(stored)
        got = media.handle(self.data_dir, {
            "op": "media.get",
            "project_id": self.project_id,
            "media_id": rec["id"],
        })
        self.assertEqual(got["status"], "BROKEN")

    def test_list_reports_broken_status(self):
        rec = self._import("a.png", PNG_BYTES, "image")
        stored = os.path.join(self.data_dir, rec["path"])
        with open(stored, "wb") as f:
            f.write(b"corrupted")
        res = media.handle(self.data_dir, {"op": "media.list", "project_id": self.project_id})
        statuses = {item["id"]: item["status"] for item in res["items"]}
        self.assertEqual(statuses[rec["id"]], "BROKEN")

    def test_broken_status_persists_across_calls(self):
        rec = self._import("a.png", PNG_BYTES, "image")
        stored = os.path.join(self.data_dir, rec["path"])
        os.remove(stored)
        first = media.handle(self.data_dir, {
            "op": "media.get", "project_id": self.project_id, "media_id": rec["id"],
        })
        self.assertEqual(first["status"], "BROKEN")
        second = media.handle(self.data_dir, {
            "op": "media.get", "project_id": self.project_id, "media_id": rec["id"],
        })
        self.assertEqual(second["status"], "BROKEN")


class TestMediaPersistence(MediaTestBase):
    def test_records_survive_reload(self):
        rec = self._import("a.png", PNG_BYTES, "image")
        # Re-import the module fresh to simulate a new process reading the store.
        fresh = _load_module("m11_media_api_fresh", os.path.join(
            "milestones", "milestone_dbb8341c8910593063a8", "api.py"))
        got = fresh.handle(self.data_dir, {
            "op": "media.get", "project_id": self.project_id, "media_id": rec["id"],
        })
        self.assertEqual(got["id"], rec["id"])
        self.assertEqual(got["sha256"], rec["sha256"])


class TestMediaValidation(MediaTestBase):
    def test_unknown_op_raises(self):
        with self.assertRaises(ValueError):
            media.handle(self.data_dir, {"op": "media.delete", "project_id": self.project_id})

    def test_missing_op_raises(self):
        with self.assertRaises(ValueError):
            media.handle(self.data_dir, {"project_id": self.project_id})

    def test_non_dict_request_raises(self):
        with self.assertRaises(ValueError):
            media.handle(self.data_dir, ["not", "a", "dict"])

    def test_empty_data_dir_raises(self):
        with self.assertRaises(ValueError):
            media.handle("", {"op": "media.list", "project_id": self.project_id})


class TestMediaApprovalIntegration(MediaTestBase):
    def _setup_content(self, media_ids):
        campaign = m4.handle(self.data_dir, {
            "op": "campaign.create",
            "project_id": self.project_id,
            "name": "C",
            "audience": "A",
            "channels": ["email"],
        })
        content = m5.handle(self.data_dir, {
            "op": "content.create",
            "project_id": self.project_id,
            "campaign_id": campaign["id"],
            "channel": "email",
            "text": "hello world",
            "claim_ids": [],
            "media_ids": media_ids,
        })
        m6.handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": content["id"],
        })
        return content

    def test_approve_succeeds_with_valid_media(self):
        rec = self._import("a.png", PNG_BYTES, "image")
        content = self._setup_content([rec["id"]])
        result = m6.handle(self.data_dir, {
            "op": "approval.approve",
            "project_id": self.project_id,
            "content_id": content["id"],
        })
        self.assertEqual(result["status"], "APPROVED")

    def test_approve_blocked_when_media_broken(self):
        rec = self._import("a.png", PNG_BYTES, "image")
        content = self._setup_content([rec["id"]])
        stored = os.path.join(self.data_dir, rec["path"])
        with open(stored, "wb") as f:
            f.write(b"corrupted")
        with self.assertRaises(ValueError):
            m6.handle(self.data_dir, {
                "op": "approval.approve",
                "project_id": self.project_id,
                "content_id": content["id"],
            })

    def test_approve_blocked_when_media_missing(self):
        rec = self._import("a.png", PNG_BYTES, "image")
        content = self._setup_content([rec["id"]])
        os.remove(os.path.join(self.data_dir, rec["path"]))
        with self.assertRaises(ValueError):
            m6.handle(self.data_dir, {
                "op": "approval.approve",
                "project_id": self.project_id,
                "content_id": content["id"],
            })


class TestMediaPublishIntegration(MediaTestBase):
    def _approved_content(self, media_ids):
        campaign = m4.handle(self.data_dir, {
            "op": "campaign.create",
            "project_id": self.project_id,
            "name": "C",
            "audience": "A",
            "channels": ["email"],
        })
        content = m5.handle(self.data_dir, {
            "op": "content.create",
            "project_id": self.project_id,
            "campaign_id": campaign["id"],
            "channel": "email",
            "text": "hello world",
            "claim_ids": [],
            "media_ids": media_ids,
        })
        m6.handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": content["id"],
        })
        m6.handle(self.data_dir, {
            "op": "approval.approve",
            "project_id": self.project_id,
            "content_id": content["id"],
        })
        return content

    def test_publish_blocked_when_media_broken_after_approval(self):
        rec = self._import("a.png", PNG_BYTES, "image")
        content = self._approved_content([rec["id"]])
        stored = os.path.join(self.data_dir, rec["path"])
        with open(stored, "wb") as f:
            f.write(b"corrupted")
        with self.assertRaises(ValueError):
            m7.handle(self.data_dir, {
                "op": "publish.send",
                "project_id": self.project_id,
                "content_id": content["id"],
                "platform_url": "http://localhost:1",
                "idempotency_key": "k1",
            })

    def test_publish_blocked_when_media_missing_after_approval(self):
        rec = self._import("a.png", PNG_BYTES, "image")
        content = self._approved_content([rec["id"]])
        os.remove(os.path.join(self.data_dir, rec["path"]))
        with self.assertRaises(ValueError):
            m7.handle(self.data_dir, {
                "op": "publish.send",
                "project_id": self.project_id,
                "content_id": content["id"],
                "platform_url": "http://localhost:1",
                "idempotency_key": "k2",
            })


if __name__ == "__main__":
    unittest.main()
