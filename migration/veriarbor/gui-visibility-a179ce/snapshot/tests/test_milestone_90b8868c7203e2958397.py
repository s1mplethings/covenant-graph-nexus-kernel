"""Tests for Milestone M4: Campaign CRUD."""

import json
import os
import shutil
import tempfile
import unittest

# Import the module under test
from milestones.milestone_90b8868c7203e2958397.api import handle as campaign_handle
# Import dependencies to set up projects
from milestones.milestone_20f2614f6ae8403d4a4e.api import handle as project_handle


class TestCampaignCRUD(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        # Create a project
        proj_res = project_handle(self.data_dir, {"op": "project.create", "name": "Test Project"})
        self.project_id = proj_res["id"]

    def tearDown(self):
        shutil.rmtree(self.data_dir)

    def _create_campaign(self, name="Launch", audience="All", channels=["email", "sms"]):
        return campaign_handle(self.data_dir, {
            "op": "campaign.create",
            "project_id": self.project_id,
            "name": name,
            "audience": audience,
            "channels": channels
        })

    def test_create_valid(self):
        res = self._create_campaign()
        self.assertIn("id", res)
        self.assertEqual(res["project_id"], self.project_id)
        self.assertEqual(res["name"], "Launch")
        self.assertEqual(res["audience"], "All")
        self.assertEqual(res["channels"], ["email", "sms"])
        self.assertEqual(res["status"], "ACTIVE")
        self.assertIsInstance(res["history"], list)
        self.assertEqual(len(res["history"]), 0) # Initial state usually has empty history or just current? Spec says appends previous. So initial is empty.

    def test_create_blank_name(self):
        with self.assertRaises(ValueError):
            self._create_campaign(name="   ")

    def test_create_blank_audience(self):
        with self.assertRaises(ValueError):
            self._create_campaign(audience="   ")

    def test_create_empty_channels(self):
        with self.assertRaises(ValueError):
            self._create_campaign(channels=[])

    def test_create_duplicate_channels(self):
        with self.assertRaises(ValueError):
            self._create_campaign(channels=["email", "email"])

    def test_create_non_string_channel(self):
        with self.assertRaises(ValueError):
            self._create_campaign(channels=["email", 123])

    def test_create_missing_project(self):
        with self.assertRaises(ValueError):
            campaign_handle(self.data_dir, {
                "op": "campaign.create",
                "project_id": "non-existent-id",
                "name": "Test",
                "audience": "Test",
                "channels": ["test"]
            })

    def test_get_success(self):
        created = self._create_campaign()
        retrieved = campaign_handle(self.data_dir, {
            "op": "campaign.get",
            "project_id": self.project_id,
            "campaign_id": created["id"]
        })
        self.assertEqual(created["id"], retrieved["id"])
        self.assertEqual(created["name"], retrieved["name"])

    def test_get_missing_id(self):
        with self.assertRaises(ValueError):
            campaign_handle(self.data_dir, {
                "op": "campaign.get",
                "project_id": self.project_id,
                "campaign_id": "invalid-id"
            })

    def test_get_cross_project(self):
        # Create another project
        other_proj = project_handle(self.data_dir, {"op": "project.create", "name": "Other"})
        other_pid = other_proj["id"]
        
        # Create campaign in first project
        c1 = self._create_campaign()
        
        # Try to get it from second project
        with self.assertRaises(ValueError):
            campaign_handle(self.data_dir, {
                "op": "campaign.get",
                "project_id": other_pid,
                "campaign_id": c1["id"]
            })

    def test_update_history_and_preserve_id(self):
        original = self._create_campaign(name="Original")
        updated = campaign_handle(self.data_dir, {
            "op": "campaign.update",
            "project_id": self.project_id,
            "campaign_id": original["id"],
            "name": "Updated",
            "audience": "VIP",
            "channels": ["push"]
        })
        
        self.assertEqual(original["id"], updated["id"])
        self.assertEqual(updated["name"], "Updated")
        self.assertEqual(updated["audience"], "VIP")
        self.assertEqual(updated["channels"], ["push"])
        
        # Check history
        self.assertEqual(len(updated["history"]), 1)
        hist_entry = updated["history"][0]
        self.assertEqual(hist_entry["name"], "Original")
        self.assertEqual(hist_entry["audience"], "All")
        self.assertEqual(hist_entry["channels"], ["email", "sms"])

    def test_update_archived_rejection(self):
        c = self._create_campaign()
        campaign_handle(self.data_dir, {
            "op": "campaign.archive",
            "project_id": self.project_id,
            "campaign_id": c["id"]
        })
        
        with self.assertRaises(ValueError):
            campaign_handle(self.data_dir, {
                "op": "campaign.update",
                "project_id": self.project_id,
                "campaign_id": c["id"],
                "name": "New Name",
                "audience": "New Audience",
                "channels": ["new"]
            })

    def test_archive_status_change(self):
        c = self._create_campaign()
        archived = campaign_handle(self.data_dir, {
            "op": "campaign.archive",
            "project_id": self.project_id,
            "campaign_id": c["id"]
        })
        self.assertEqual(archived["status"], "ARCHIVED")

    def test_archive_error_cases(self):
        with self.assertRaises(ValueError):
            campaign_handle(self.data_dir, {
                "op": "campaign.archive",
                "project_id": self.project_id,
                "campaign_id": "invalid-id"
            })

    def test_list_all_items(self):
        c1 = self._create_campaign(name="C1")
        c2 = self._create_campaign(name="C2")
        
        res = campaign_handle(self.data_dir, {
            "op": "campaign.list",
            "project_id": self.project_id
        })
        
        items = res["items"]
        self.assertEqual(len(items), 2)
        ids = [i["id"] for i in items]
        self.assertIn(c1["id"], ids)
        self.assertIn(c2["id"], ids)

    def test_persistence_across_restart(self):
        # Simulate restart by clearing any in-memory caches (though this impl uses files directly)
        # Just re-read via new call
        c = self._create_campaign()
        
        # Verify file exists
        path = os.path.join(self.data_dir, "campaigns.json")
        self.assertTrue(os.path.exists(path))
        
        # Read raw JSON to verify structure
        with open(path, 'r') as f:
            data = json.load(f)
            found = False
            for item in data:
                if item["id"] == c["id"]:
                    found = True
                    break
            self.assertTrue(found)

    def test_project_isolation_same_dir(self):
        # Create second project in same data_dir
        p2 = project_handle(self.data_dir, {"op": "project.create", "name": "Project 2"})
        pid2 = p2["id"]
        
        # Create campaign in P1
        c1 = self._create_campaign(name="P1 Campaign")
        
        # List campaigns for P2 should be empty
        res_p2 = campaign_handle(self.data_dir, {
            "op": "campaign.list",
            "project_id": pid2
        })
        self.assertEqual(len(res_p2["items"]), 0)
        
        # List campaigns for P1 should have 1
        res_p1 = campaign_handle(self.data_dir, {
            "op": "campaign.list",
            "project_id": self.project_id
        })
        self.assertEqual(len(res_p1["items"]), 1)
        self.assertEqual(res_p1["items"][0]["id"], c1["id"])

if __name__ == "__main__":
    unittest.main()