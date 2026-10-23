import json
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from caldova import cloud, region

ACCOUNT = "/subscriptions/s/resourceGroups/rg-caldova-demo/providers/Microsoft.CognitiveServices/accounts/caldova-harness-centralus-abc"
OTHER = "/subscriptions/s/resourceGroups/rg-caldova-demo/providers/Microsoft.CognitiveServices/accounts/caldova-abc"


def change(kind, rid):
    return {"changeType": kind, "resourceId": rid}


class GuardTests(unittest.TestCase):
    def test_new_account_namespace_may_be_created(self):
        region.check_whatif([
            change("Create", ACCOUNT), change("Create", ACCOUNT + "/projects/capability-lab"),
            change("Create", ACCOUNT + "/providers/Microsoft.Authorization/roleAssignments/x"),
            change("NoChange", OTHER), change("Ignore", "/subscriptions/s/other"),
        ], ACCOUNT)

    def test_rejects_changes_outside_namespace_including_prefix_lookalike(self):
        for kind in ("Create", "Modify", "Deploy", "Unsupported"):
            with self.assertRaises(RuntimeError):
                region.check_whatif([change(kind, OTHER)], ACCOUNT)
        with self.assertRaises(RuntimeError):
            region.check_whatif([change("Modify", ACCOUNT + "-two")], ACCOUNT)

    def test_rejects_any_delete(self):
        for rid in (ACCOUNT, ACCOUNT + "/deployments/gpt-5-mini", OTHER):
            with self.assertRaises(RuntimeError):
                region.check_whatif([change("Delete", rid)], ACCOUNT)


class QuotaTests(unittest.TestCase):
    def test_rerun_counts_existing_regional_allocation(self):
        self.assertEqual(region.additional_capacity(400, 0), 400)
        self.assertEqual(region.additional_capacity(400, 400), 0)
        self.assertEqual(region.additional_capacity(400, 500), 0)
        self.assertEqual(region.additional_capacity(400, 150), 250)

    def test_headroom_boundary(self):
        row = {"currentValue": 600.0, "limit": 1000.0}
        self.assertEqual(region.check_quota(row, 400)["available"], 400)
        with self.assertRaises(RuntimeError):
            region.check_quota(row, 401)
        region.check_quota({"currentValue": 1000.0, "limit": 1000.0}, 0)


class CatalogAndPolicyTests(unittest.TestCase):
    def item(self, version="2025-08-07", skus=("GlobalStandard",), kind="OpenAI"):
        return {"kind": kind, "model": {"format": "OpenAI", "name": "gpt-5-mini", "version": version,
                                        "lifecycleStatus": "GenerallyAvailable",
                                        "skus": [{"name": s, "usageName": f"OpenAI.{s}.gpt-5-mini"} for s in skus]}}

    def test_selects_exact_model_version_sku(self):
        found = region.select_model({"value": [self.item("2025-01-01"), self.item()]})
        self.assertEqual(found["usageName"], "OpenAI.GlobalStandard.gpt-5-mini")

    def test_missing_offer_fails(self):
        for value in ([], [self.item(kind="AIServices")], [self.item(skus=("DataZoneStandard",))]):
            with self.assertRaises(RuntimeError):
                region.select_model({"value": value})

    def test_policy_requires_listed_region(self):
        self.assertIn("centralus", region.parse_policy({"regions": ["centralus"]}, "centralus"))
        for payload in ({"regions": ["westus2"]}, {"regions": []}, {}, []):
            with self.assertRaises(RuntimeError):
                region.parse_policy(payload, "centralus")

    def test_account_name_is_derived_from_main_suffix(self):
        self.assertEqual(region.account_name("caldova-abc123", "centralus"), "caldova-harness-centralus-abc123")
        with self.assertRaises(ValueError):
            region.account_name("other-abc", "centralus")


class StateTests(unittest.TestCase):
    main: ClassVar[dict] = {
        "tenant": "t", "subscription": "s", "principal_id": "p", "mcp_app_id": "a",
        "mcp_application_object_id": "o", "mcp_service_principal_id": "sp",
        "outputs": {"AZURE_RESOURCE_GROUP": "rg-caldova-demo", "AZURE_CONTAINER_REGISTRY_ENDPOINT": "r.io",
                    "AZURE_CONTAINER_REGISTRY_NAME": "r", "MCP_ENDPOINT": "https://mcp", "MCP_AUDIENCE": "aud",
                    "MCP_HOST_NAME": "mcp", "FOUNDRY_ACCOUNT_NAME": "caldova-abc",
                    "FOUNDRY_PROJECT_ENDPOINT": "https://east", "FOUNDRY_MODEL": "gpt-5-mini"},
        "agents": {"east": {"version": "1"}}, "skills": {"east": {}}, "toolboxes": {"east": {}},
    }
    deployed: ClassVar[dict] = {"accountName": "caldova-harness-centralus-abc", "projectEndpoint": "https://central"}

    def test_main_is_unchanged_and_east_state_is_not_copied(self):
        with tempfile.TemporaryDirectory() as folder:
            main_path, secondary = Path(folder, "lab.json"), Path(folder, "harness-region.json")
            cloud.save_state(self.main, main_path)
            before = main_path.read_bytes()
            region.write_secondary_state(main_path, secondary, self.deployed, "centralus")
            self.assertEqual(main_path.read_bytes(), before)
            state = json.loads(secondary.read_text())
            self.assertEqual(state["outputs"]["FOUNDRY_PROJECT_ENDPOINT"], "https://central")
            self.assertEqual(state["outputs"]["MCP_ENDPOINT"], "https://mcp")
            self.assertNotIn("agents", state)
            self.assertNotIn("toolboxes", state)

    def test_rerun_preserves_same_project_state_only(self):
        with tempfile.TemporaryDirectory() as folder:
            main_path, secondary = Path(folder, "lab.json"), Path(folder, "harness-region.json")
            cloud.save_state(self.main, main_path)
            region.write_secondary_state(main_path, secondary, self.deployed, "centralus")
            state = json.loads(secondary.read_text())
            state["agents"] = {"harness": {"version": "3"}}
            cloud.save_state(state, secondary)
            region.write_secondary_state(main_path, secondary, self.deployed, "centralus")
            self.assertEqual(json.loads(secondary.read_text())["agents"], {"harness": {"version": "3"}})
            region.write_secondary_state(main_path, secondary,
                                         {"accountName": "other", "projectEndpoint": "https://new"}, "centralus")
            self.assertNotIn("agents", json.loads(secondary.read_text()))


if __name__ == "__main__":
    unittest.main()
