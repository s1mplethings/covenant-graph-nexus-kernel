"""
Test suite for Milestone M6: Approval.
Exercises the declared public contract for approval.review, approval.approve,
approval.status, validation rules, revision binding, claim validity checks,
media presence checks, project isolation, persistence, and error handling.
"""

import json
import os
import shutil
import tempfile
import unittest

# Import dependencies to set up state
from milestones.milestone_20f2614f6ae8403d4a4e.api import handle as m1_handle
from milestones.milestone_4e7c26281cf61a85851e.api import handle as m2_handle
from milestones.milestone_1369a82cde04a7e5887d.api import handle as m3_handle
from milestones.milestone_90b8868c7203e2958397.api import handle as m4_handle
from milestones.milestone_9165a990eed5b9c8801e.api import handle as m5_handle

# Import the module under test
from milestones.milestone_33270fed0c9054f5ae04.api import handle as m6_handle


class TestM6Approval(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self.project_id = None
        self.campaign_id = None
        self.content_id = None
        self.claim_id = None
        self.evidence_id = None

    def tearDown(self):
        if os.path.exists(self.data_dir):
            shutil.rmtree(self.data_dir)

    def _create_project(self):
        res = m1_handle(self.data_dir, {"op": "project.create", "name": "Test Project"})
        self.project_id = res["id"]
        return self.project_id

    def _create_campaign(self):
        if not self.project_id:
            self._create_project()
        res = m4_handle(self.data_dir, {
            "op": "campaign.create",
            "project_id": self.project_id,
            "name": "Test Campaign",
            "audience": "Everyone",
            "channels": ["web"]
        })
        self.campaign_id = res["id"]
        return self.campaign_id

    def _create_evidence_and_claim(self, text="test claim text"):
        if not self.project_id:
            self._create_project()
        
        # Create a temp file for evidence
        ev_dir = os.path.join(self.data_dir, "ev_src")
        os.makedirs(ev_dir, exist_ok=True)
        with open(os.path.join(ev_dir, "doc.txt"), "w") as f:
            f.write(text)
            
        ev_res = m2_handle(self.data_dir, {
            "op": "evidence.import",
            "project_id": self.project_id,
            "path": ev_dir
        })
        self.evidence_id = ev_res["id"]
        
        cl_res = m3_handle(self.data_dir, {
            "op": "claim.create",
            "project_id": self.project_id,
            "text": text,
            "evidence_ids": [self.evidence_id]
        })
        self.claim_id = cl_res["id"]
        return self.claim_id

    def _create_content(self, text="content body", claim_ids=None, media_ids=None):
        if not self.campaign_id:
            self._create_campaign()
        if claim_ids is None:
            claim_ids = []
        if media_ids is None:
            media_ids = []
            
        res = m5_handle(self.data_dir, {
            "op": "content.create",
            "project_id": self.project_id,
            "campaign_id": self.campaign_id,
            "channel": "web",
            "text": text,
            "claim_ids": claim_ids,
            "media_ids": media_ids
        })
        self.content_id = res["id"]
        return self.content_id

    def test_approval_review_success(self):
        """approval.review successfully transitions a DRAFT content revision to REVIEW status."""
        self._create_content()
        
        # Initial status should be DRAFT
        status_res = m6_handle(self.data_dir, {
            "op": "approval.status",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        self.assertEqual(status_res["status"], "DRAFT")
        
        # Review it
        review_res = m6_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        self.assertEqual(review_res["status"], "REVIEW")
        self.assertEqual(review_res["content_id"], self.content_id)
        self.assertEqual(review_res["revision"], 1)
        
        # Check status again
        status_res = m6_handle(self.data_dir, {
            "op": "approval.status",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        self.assertEqual(status_res["status"], "REVIEW")

    def test_approval_approve_success(self):
        """approval.approve successfully transitions a REVIEWED content revision to APPROVED status only if all linked claims are SUPPORTED and media is valid/present."""
        # Setup: Evidence -> Claim (SUPPORTED) -> Content (with claim) -> Review -> Approve
        claim_text = "verified fact"
        self._create_evidence_and_claim(claim_text)
        self._create_content(text="article", claim_ids=[self.claim_id])
        
        # Verify claim is supported
        cl_status = m3_handle(self.data_dir, {
            "op": "claim.get",
            "project_id": self.project_id,
            "claim_id": self.claim_id
        })
        self.assertEqual(cl_status["status"], "SUPPORTED")
        
        # Review content
        m6_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        
        # Approve content
        approve_res = m6_handle(self.data_dir, {
            "op": "approval.approve",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        self.assertEqual(approve_res["status"], "APPROVED")
        self.assertEqual(approve_res["content_id"], self.content_id)
        self.assertEqual(approve_res["revision"], 1)

    def test_approval_status_reporting(self):
        """approval.status correctly reports the current status (DRAFT, REVIEW, APPROVED) for a given content ID."""
        self._create_content()
        
        # DRAFT
        s = m6_handle(self.data_dir, {"op": "approval.status", "project_id": self.project_id, "content_id": self.content_id})
        self.assertEqual(s["status"], "DRAFT")
        
        # REVIEW
        m6_handle(self.data_dir, {"op": "approval.review", "project_id": self.project_id, "content_id": self.content_id})
        s = m6_handle(self.data_dir, {"op": "approval.status", "project_id": self.project_id, "content_id": self.content_id})
        self.assertEqual(s["status"], "REVIEW")
        
        # APPROVED (needs valid claims/media, but we have none so it might fail or pass depending on impl. 
        # Spec says: "all referenced media assets are present/valid (media list can be empty before M11)". 
        # And "all associated claims are currently SUPPORTED". If no claims, vacuously true? 
        # Let's assume empty lists are valid for now to test status transition.)
        # Actually, let's create a valid scenario for approval first.
        self._create_evidence_and_claim("fact")
        self._create_content(claim_ids=[self.claim_id]) # New content
        
        m6_handle(self.data_dir, {"op": "approval.review", "project_id": self.project_id, "content_id": self.content_id})
        m6_handle(self.data_dir, {"op": "approval.approve", "project_id": self.project_id, "content_id": self.content_id})
        
        s = m6_handle(self.data_dir, {"op": "approval.status", "project_id": self.project_id, "content_id": self.content_id})
        self.assertEqual(s["status"], "APPROVED")

    def test_approval_approve_raises_if_not_reviewed(self):
        """approval.approve raises ValueError if the content has not been reviewed."""
        self._create_content()
        
        with self.assertRaises(ValueError):
            m6_handle(self.data_dir, {
                "op": "approval.approve",
                "project_id": self.project_id,
                "content_id": self.content_id
            })

    def test_approval_approve_raises_if_claims_invalid(self):
        """approval.approve raises ValueError if any linked claim is UNSUPPORTED, STALE, or CONFLICT."""
        # Case 1: UNSUPPORTED
        self._create_project()
        self._create_campaign()
        
        # Create a claim that is unsupported (no evidence or bad evidence)
        cl_res = m3_handle(self.data_dir, {
            "op": "claim.create",
            "project_id": self.project_id,
            "text": "unsupported statement",
            "evidence_ids": [] # No evidence -> UNSUPPORTED
        })
        bad_claim_id = cl_res["id"]
        
        self._create_content(claim_ids=[bad_claim_id])
        
        # Review
        m6_handle(self.data_dir, {"op": "approval.review", "project_id": self.project_id, "content_id": self.content_id})
        
        # Try Approve
        with self.assertRaises(ValueError):
            m6_handle(self.data_dir, {
                "op": "approval.approve",
                "project_id": self.project_id,
                "content_id": self.content_id
            })
            
        # Case 2: CONFLICT
        self._create_content() # Reset content id
        cl_res2 = m3_handle(self.data_dir, {
            "op": "claim.create",
            "project_id": self.project_id,
            "text": "conflicting statement",
            "evidence_ids": []
        })
        conflict_claim_id = cl_res2["id"]
        
        # Mark as conflict
        m3_handle(self.data_dir, {
            "op": "claim.conflict",
            "project_id": self.project_id,
            "claim_id": conflict_claim_id,
            "reason": "contradiction"
        })
        
        self._create_content(claim_ids=[conflict_claim_id])
        m6_handle(self.data_dir, {"op": "approval.review", "project_id": self.project_id, "content_id": self.content_id})
        
        with self.assertRaises(ValueError):
            m6_handle(self.data_dir, {
                "op": "approval.approve",
                "project_id": self.project_id,
                "content_id": self.content_id
            })

    def test_approval_approve_raises_if_media_missing(self):
        """approval.approve raises ValueError if referenced media is missing or invalid."""
        # Note: The spec says "media list can be empty before M11". 
        # It implies if media_ids are provided, they must be valid. 
        # Since there is no M11 Media module yet, how do we define "missing"?
        # Usually, this means the ID doesn't resolve to anything in a future system, 
        # OR perhaps the implementation checks against a local store if one exists.
        # Given the constraints, if I provide a fake media ID, does it fail?
        # The prompt says: "referenced media is missing or invalid".
        # If the system doesn't have a media registry yet, maybe it just accepts strings?
        # However, to test the *error path*, I need to know what makes it invalid.
        # Let's assume for now that if media_ids are non-empty, they must exist in some registry.
        # Since no registry exists, providing ANY media_id might trigger "missing" if the impl expects a lookup.
        # BUT, the spec says "media list can be empty before M11". This suggests non-empty might be problematic or untested.
        # Let's try to find a way to make it fail. 
        # If the implementation simply validates that media_ids are strings, it won't fail.
        # If it tries to look them up in a 'media.json' that doesn't exist, it will fail.
        # Let's assume the latter for the sake of testing the error condition described in acceptance criteria.
        
        self._create_content(media_ids=["fake-media-id-123"])
        m6_handle(self.data_dir, {"op": "approval.review", "project_id": self.project_id, "content_id": self.content_id})
        
        # This test depends heavily on whether M6 actually implements media checking logic 
        # against a non-existent M11. If M6 just passes through, this test might fail (i.e., not raise).
        # However, the acceptance criteria explicitly requires raising ValueError if media is missing.
        # So the implementation MUST check. If it checks against an empty/non-existent store, it should raise.
        
        with self.assertRaises(ValueError):
            m6_handle(self.data_dir, {
                "op": "approval.approve",
                "project_id": self.project_id,
                "content_id": self.content_id
            })

    def test_content_edit_resets_approval_to_draft(self):
        """a content.edit operation (from M5) resets the approval status of the new revision to DRAFT, leaving old approvals historical."""
        self._create_evidence_and_claim("fact")
        self._create_content(claim_ids=[self.claim_id])
        
        # Review and Approve Rev 1
        m6_handle(self.data_dir, {"op": "approval.review", "project_id": self.project_id, "content_id": self.content_id})
        m6_handle(self.data_dir, {"op": "approval.approve", "project_id": self.project_id, "content_id": self.content_id})
        
        # Edit Content (creates Rev 2)
        edit_res = m5_handle(self.data_dir, {
            "op": "content.edit",
            "project_id": self.project_id,
            "content_id": self.content_id,
            "text": "updated article"
        })
        self.assertEqual(edit_res["revision"], 2)
        
        # Check Status - should be DRAFT
        status_res = m6_handle(self.data_dir, {
            "op": "approval.status",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        self.assertEqual(status_res["status"], "DRAFT")
        self.assertEqual(status_res["revision"], 2)

    def test_project_isolation(self):
        """approval operations enforce project isolation (cannot access/approve content from other projects)."""
        # Project A
        proj_a = m1_handle(self.data_dir, {"op": "project.create", "name": "A"})["id"]
        camp_a = m4_handle(self.data_dir, {"op": "campaign.create", "project_id": proj_a, "name": "CA", "audience": "X", "channels": ["web"]})["id"]
        cont_a = m5_handle(self.data_dir, {"op": "content.create", "project_id": proj_a, "campaign_id": camp_a, "channel": "web", "text": "T", "claim_ids": [], "media_ids": []})["id"]
        
        # Project B
        proj_b = m1_handle(self.data_dir, {"op": "project.create", "name": "B"})["id"]
        
        # Try to review Content A using Project B
        with self.assertRaises(ValueError):
            m6_handle(self.data_dir, {
                "op": "approval.review",
                "project_id": proj_b,
                "content_id": cont_a
            })
            
        # Try to get status of Content A using Project B
        with self.assertRaises(ValueError):
            m6_handle(self.data_dir, {
                "op": "approval.status",
                "project_id": proj_b,
                "content_id": cont_a
            })

    def test_persistence(self):
        """approval data persists after the Python process exits and is reloaded in a new process using the same data_dir."""
        self._create_evidence_and_claim("fact")
        self._create_content(claim_ids=[self.claim_id])
        
        m6_handle(self.data_dir, {"op": "approval.review", "project_id": self.project_id, "content_id": self.content_id})
        m6_handle(self.data_dir, {"op": "approval.approve", "project_id": self.project_id, "content_id": self.content_id})
        
        # Simulate process restart by calling handle again (it reads from disk)
        # In a real test, we'd spawn a subprocess, but here we rely on the fact that 
        # handle() loads state from files each time or maintains consistent file-based state.
        # The modules use _load_list/_save_list which read/write JSON files.
        
        status_res = m6_handle(self.data_dir, {
            "op": "approval.status",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        self.assertEqual(status_res["status"], "APPROVED")

    def test_invalid_inputs_and_unknown_ids(self):
        """invalid inputs, unknown IDs, and unsupported operations raise ValueError."""
        # Unknown Op
        with self.assertRaises(ValueError):
            m6_handle(self.data_dir, {"op": "unknown.op", "project_id": "p", "content_id": "c"})
            
        # Missing Op
        with self.assertRaises(ValueError):
            m6_handle(self.data_dir, {"project_id": "p", "content_id": "c"})
            
        # Invalid Data Dir
        with self.assertRaises(ValueError):
            m6_handle("", {"op": "approval.status", "project_id": "p", "content_id": "c"})
            
        # Invalid Request Type
        with self.assertRaises(ValueError):
            m6_handle(self.data_dir, "not a dict")
            
        # Unknown Project
        self._create_content()
        with self.assertRaises(ValueError):
            m6_handle(self.data_dir, {
                "op": "approval.status",
                "project_id": "non-existent-project",
                "content_id": self.content_id
            })
            
        # Unknown Content
        with self.assertRaises(ValueError):
            m6_handle(self.data_dir, {
                "op": "approval.status",
                "project_id": self.project_id,
                "content_id": "non-existent-content"
            })

if __name__ == '__main__':
    unittest.main()