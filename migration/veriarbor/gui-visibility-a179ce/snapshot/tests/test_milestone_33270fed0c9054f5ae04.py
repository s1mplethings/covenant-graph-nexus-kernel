"""Tests for Milestone M6: Approval."""

import json
import os
import shutil
import tempfile
import unittest
import uuid

# Import the module under test
from milestones.milestone_33270fed0c9054f5ae04.api import handle as approval_handle

# Import dependencies to set up state
from milestones.milestone_20f2614f6ae8403d4a4e.api import handle as project_handle
from milestones.milestone_4e7c26281cf61a85851e.api import handle as evidence_handle
from milestones.milestone_1369a82cde04a7e5887d.api import handle as claim_handle
from milestones.milestone_90b8868c7203e2958397.api import handle as campaign_handle
from milestones.milestone_9165a990eed5b9c8801e.api import handle as content_handle


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

    def _create_project(self, name="Test Project"):
        res = project_handle(self.data_dir, {"op": "project.create", "name": name})
        return res["id"]

    def _create_campaign(self, project_id, name="Test Campaign", audience="Audience", channels=None):
        if channels is None:
            channels = ["web"]
        res = campaign_handle(self.data_dir, {
            "op": "campaign.create",
            "project_id": project_id,
            "name": name,
            "audience": audience,
            "channels": channels
        })
        return res["id"]

    def _create_evidence(self, project_id, source_path, text_content):
        # Create a file in source_path
        os.makedirs(source_path, exist_ok=True)
        filepath = os.path.join(source_path, "test.txt")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(text_content)
        
        res = evidence_handle(self.data_dir, {
            "op": "evidence.import",
            "project_id": project_id,
            "path": source_path
        })
        return res["id"]

    def _create_claim(self, project_id, text, evidence_ids):
        res = claim_handle(self.data_dir, {
            "op": "claim.create",
            "project_id": project_id,
            "text": text,
            "evidence_ids": evidence_ids
        })
        return res["id"], res["status"]

    def _create_content(self, project_id, campaign_id, channel, text, claim_ids=None, media_ids=None):
        if claim_ids is None:
            claim_ids = []
        if media_ids is None:
            media_ids = []
        res = content_handle(self.data_dir, {
            "op": "content.create",
            "project_id": project_id,
            "campaign_id": campaign_id,
            "channel": channel,
            "text": text,
            "claim_ids": claim_ids,
            "media_ids": media_ids
        })
        return res["id"], res["revision"], res["status"]

    def _edit_content(self, project_id, content_id, text, claim_ids=None, media_ids=None):
        req = {
            "op": "content.edit",
            "project_id": project_id,
            "content_id": content_id,
            "text": text
        }
        if claim_ids is not None:
            req["claim_ids"] = claim_ids
        if media_ids is not None:
            req["media_ids"] = media_ids
        res = content_handle(self.data_dir, req)
        return res["id"], res["revision"], res["status"]

    def _setup_full_valid_state(self):
        """Helper to create a project, campaign, evidence, supported claim, and content linked to it."""
        self.project_id = self._create_project()
        self.campaign_id = self._create_campaign(self.project_id)
        
        # Evidence dir
        ev_dir = os.path.join(self.data_dir, "ev_src")
        self.evidence_id = self._create_evidence(self.project_id, ev_dir, "The sky is blue.")
        
        # Claim that matches evidence
        self.claim_id, status = self._create_claim(self.project_id, "sky is blue", [self.evidence_id])
        self.assertEqual(status, "SUPPORTED")
        
        # Content linking the claim
        self.content_id, rev, stat = self._create_content(
            self.project_id, 
            self.campaign_id, 
            "web", 
            "Draft content about sky", 
            claim_ids=[self.claim_id]
        )
        self.assertEqual(stat, "DRAFT")

    def test_approval_review_success(self):
        """approval.review successfully transitions DRAFT to REVIEW."""
        self._setup_full_valid_state()
        
        res = approval_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        
        self.assertEqual(res["content_id"], self.content_id)
        self.assertEqual(res["status"], "REVIEW")
        self.assertIn("revision", res)

    def test_approval_approve_success(self):
        """approval.approve successfully transitions REVIEWED to APPROVED when claims are SUPPORTED."""
        self._setup_full_valid_state()
        
        # First review
        approval_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        
        # Then approve
        res = approval_handle(self.data_dir, {
            "op": "approval.approve",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        
        self.assertEqual(res["content_id"], self.content_id)
        self.assertEqual(res["status"], "APPROVED")

    def test_approval_status_report(self):
        """approval.status correctly reports current status."""
        self._setup_full_valid_state()
        
        # Initial DRAFT
        res = approval_handle(self.data_dir, {
            "op": "approval.status",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        self.assertEqual(res["status"], "DRAFT")
        
        # After Review
        approval_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        res = approval_handle(self.data_dir, {
            "op": "approval.status",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        self.assertEqual(res["status"], "REVIEW")
        
        # After Approve
        approval_handle(self.data_dir, {
            "op": "approval.approve",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        res = approval_handle(self.data_dir, {
            "op": "approval.status",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        self.assertEqual(res["status"], "APPROVED")

    def test_approve_raises_if_not_reviewed(self):
        """approval.approve raises ValueError if content has not been reviewed."""
        self._setup_full_valid_state()
        
        with self.assertRaises(ValueError):
            approval_handle(self.data_dir, {
                "op": "approval.approve",
                "project_id": self.project_id,
                "content_id": self.content_id
            })

    def test_approve_raises_if_claim_unsupported(self):
        """approval.approve raises ValueError if any linked claim is UNSUPPORTED."""
        self._setup_full_valid_state()
        
        # Create a new claim that is unsupported (no evidence or mismatch)
        bad_claim_id, _ = self._create_claim(self.project_id, "The moon is cheese", [])
        
        # Edit content to link this bad claim
        self._edit_content(self.project_id, self.content_id, "Updated text", claim_ids=[bad_claim_id])
        
        # Review the new revision
        approval_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        
        # Try to approve - should fail because claim is UNSUPPORTED
        with self.assertRaises(ValueError):
            approval_handle(self.data_dir, {
                "op": "approval.approve",
                "project_id": self.project_id,
                "content_id": self.content_id
            })

    def test_approve_raises_if_claim_stale(self):
        """approval.approve raises ValueError if any linked claim is STALE."""
        self._setup_full_valid_state()
        
        # Supersede the evidence used by the claim
        ev_dir = os.path.join(self.data_dir, "ev_src")
        # Modify file to trigger refresh/supersede logic in M2? 
        # Actually, M2 evidence.refresh creates a new ID and marks old as SUPERSEDED.
        # But our claim links to the OLD evidence ID. 
        # If we refresh evidence, the old one becomes SUPERSEDED.
        # The claim's status computation checks if ALL cited evidence are SUPERSEDED -> STALE.
        
        # Let's just manually manipulate the evidence.json to mark it SUPERSEDED for simplicity of test setup,
        # OR use the API properly.
        # Using API: evidence.refresh requires the same path but changed content?
        # If content is same, it returns same record. We need different content.
        
        filepath = os.path.join(ev_dir, "test.txt")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("Different content now.")
            
        # Refresh evidence
        evidence_handle(self.data_dir, {
            "op": "evidence.refresh",
            "project_id": self.project_id,
            "evidence_id": self.evidence_id
        })
        
        # Now the original evidence_id points to a SUPERSEDED record.
        # The claim still cites the original evidence_id.
        # When we check claim status via get/list, it should be STALE.
        
        # Verify claim is stale
        claim_res = claim_handle(self.data_dir, {
            "op": "claim.get",
            "project_id": self.project_id,
            "claim_id": self.claim_id
        })
        self.assertEqual(claim_res["status"], "STALE")
        
        # Review content again (it might have reset to draft on edit, but we didn't edit content, just evidence)
        # Wait, does changing evidence change content status? No. Content status is independent.
        # But approval.approve checks CLAIM validity at time of approval.
        
        # Ensure content is in REVIEW state
        approval_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        
        # Try to approve
        with self.assertRaises(ValueError):
            approval_handle(self.data_dir, {
                "op": "approval.approve",
                "project_id": self.project_id,
                "content_id": self.content_id
            })

    def test_approve_raises_if_claim_conflict(self):
        """approval.approve raises ValueError if any linked claim is CONFLICT."""
        self._setup_full_valid_state()
        
        # Mark claim as conflict
        claim_handle(self.data_dir, {
            "op": "claim.conflict",
            "project_id": self.project_id,
            "claim_id": self.claim_id,
            "reason": "Contradictory data"
        })
        
        # Review content
        approval_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        
        # Try to approve
        with self.assertRaises(ValueError):
            approval_handle(self.data_dir, {
                "op": "approval.approve",
                "project_id": self.project_id,
                "content_id": self.content_id
            })

    def test_approve_raises_if_media_missing(self):
        """approval.approve raises ValueError if referenced media is missing or invalid."""
        self._setup_full_valid_state()
        
        # Add a fake media ID to content
        fake_media_id = "nonexistent-media-id"
        self._edit_content(self.project_id, self.content_id, "Text with media", media_ids=[fake_media_id])
        
        # Review
        approval_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        
        # Try to approve
        with self.assertRaises(ValueError):
            approval_handle(self.data_dir, {
                "op": "approval.approve",
                "project_id": self.project_id,
                "content_id": self.content_id
            })

    def test_edit_resets_to_draft(self):
        """A content.edit operation resets the approval status of the new revision to DRAFT."""
        self._setup_full_valid_state()
        
        # Review and Approve
        approval_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        approval_handle(self.data_dir, {
            "op": "approval.approve",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        
        # Check status is APPROVED
        res = approval_handle(self.data_dir, {
            "op": "approval.status",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        self.assertEqual(res["status"], "APPROVED")
        
        # Edit content
        self._edit_content(self.project_id, self.content_id, "New text version")
        
        # Check status is DRAFT
        res = approval_handle(self.data_dir, {
            "op": "approval.status",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        self.assertEqual(res["status"], "DRAFT")

    def test_project_isolation(self):
        """Approval operations enforce project isolation."""
        self._setup_full_valid_state()
        
        # Create another project
        other_project_id = self._create_project(name="Other Project")
        
        # Try to review content from first project using second project ID
        with self.assertRaises(ValueError):
            approval_handle(self.data_dir, {
                "op": "approval.review",
                "project_id": other_project_id,
                "content_id": self.content_id
            })
            
        # Try to approve content from first project using second project ID
        with self.assertRaises(ValueError):
            approval_handle(self.data_dir, {
                "op": "approval.approve",
                "project_id": other_project_id,
                "content_id": self.content_id
            })

    def test_persistence(self):
        """Approval data persists after process exits and reloads."""
        self._setup_full_valid_state()
        
        # Review
        approval_handle(self.data_dir, {
            "op": "approval.review",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        
        # Simulate process restart by creating a new handle instance (though handle is stateless function, 
        # the data is on disk). We just call it again.
        # To strictly test persistence, we can verify the file exists or just rely on the fact that 
        # subsequent calls read from disk.
        
        res = approval_handle(self.data_dir, {
            "op": "approval.status",
            "project_id": self.project_id,
            "content_id": self.content_id
        })
        self.assertEqual(res["status"], "REVIEW")

    def test_invalid_inputs(self):
        """Invalid inputs raise ValueError."""
        self._setup_full_valid_state()
        
        # Unknown op
        with self.assertRaises(ValueError):
            approval_handle(self.data_dir, {
                "op": "unknown.op",
                "project_id": self.project_id,
                "content_id": self.content_id
            })
            
        # Missing project_id
        with self.assertRaises(ValueError):
            approval_handle(self.data_dir, {
                "op": "approval.review",
                "content_id": self.content_id
            })
            
        # Missing content_id
        with self.assertRaises(ValueError):
            approval_handle(self.data_dir, {
                "op": "approval.review",
                "project_id": self.project_id
            })
            
        # Invalid project_id (not found)
        with self.assertRaises(ValueError):
            approval_handle(self.data_dir, {
                "op": "approval.review",
                "project_id": "invalid-project-id",
                "content_id": self.content_id
            })
            
        # Invalid content_id (not found)
        with self.assertRaises(ValueError):
            approval_handle(self.data_dir, {
                "op": "approval.review",
                "project_id": self.project_id,
                "content_id": "invalid-content-id"
            })

if __name__ == '__main__':
    unittest.main()