import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from caldova import cloud
from caldova.experiments import (
    Foundry,
    create_agents,
    native_skill_diagnostic,
    run_discovery,
    run_spill,
)
from caldova.fixtures import expected_markers


class ExperimentTests(unittest.TestCase):
    def test_records_feature_header_before_transport_without_credentials(self):
        api = Foundry.__new__(Foundry)
        api.endpoint = "https://example.test"
        api.client = Mock()
        api.client.request.side_effect = RuntimeError("transport failed")
        with patch("caldova.experiments.record") as record, \
                self.assertRaisesRegex(RuntimeError, "transport failed"):
            api.call("POST", "/agents/test/versions", name="case", body={"definition": {}},
                     headers={"Foundry-Features": "Skills=V1Preview", "Authorization": "private-token"})
        recorded = record.call_args.args[1]
        self.assertEqual(recorded["foundry_features"], "Skills=V1Preview")
        self.assertNotIn("private-token", json.dumps(recorded))

    def test_missing_or_incomplete_skill_answer_is_a_functional_failure(self):
        for text, status, expected in (
            ("unavailable", "completed", "FAIL"),
            ("secret-marker", "incomplete", "FAIL"),
            ("secret-marker", "completed", "PASS"),
        ):
            with self.subTest(text=text, status=status):
                api = Mock()
                api.endpoint = "https://example.test/project"
                api.state = {
                    "outputs": {"FOUNDRY_MODEL": "model"},
                    "skills": {"caldova-orchard": {"version": "2", "marker": "secret-marker"}},
                }
                api.call.side_effect = [
                    {"version": "14"},
                    {"status": status, "output": [{"type": "message", "content": [{"text": text}]}]},
                ]
                with patch("caldova.experiments.Foundry", return_value=api), \
                        patch("caldova.experiments.record") as record, patch("builtins.print"):
                    native_skill_diagnostic()
                self.assertEqual(record.call_args.args[1]["status"], expected)
                self.assertEqual(record.call_args.args[1]["loading_mechanism"], "INDETERMINATE")
                self.assertEqual(record.call_args.args[1]["project_endpoint"], api.endpoint)

    def test_spill_requires_completed_compact_marker_values(self):
        markers = expected_markers(1024, "test-run")
        compact = "\n".join([markers["BEGIN"], markers["MIDDLE"]])
        for text, status, correct in (
            (compact, "completed", True),
            (compact + "\nextra payload", "completed", False),
            (compact, "incomplete", False),
        ):
            with self.subTest(status=status, correct=correct):
                api = Mock()
                api.endpoint = "https://example.test/project"
                api.state = {"agents": {"caldova-prompt": {"version": "7"}}}
                api.call.side_effect = [
                    {"id": "response", "status": status,
                     "output": [{"type": "message", "content": [{"text": text}]}]},
                    {"output": []},
                ]
                with patch("caldova.experiments.Foundry", return_value=api), \
                        patch("caldova.experiments.uuid.uuid4", return_value=SimpleNamespace(hex="test-run")), \
                        patch("caldova.experiments.record") as record:
                    run_spill([1024])
                self.assertEqual(record.call_args_list[0].args[1]["answer_correct"], correct)
                self.assertIn("exactly 24 hexadecimal characters", api.call.call_args_list[0].kwargs["body"]["input"])

    def test_toolbox_skill_failure_is_recorded_separately_from_greeting(self):
        api = Mock()
        api.endpoint = "https://example.test/project"
        api.state = {
            "outputs": {"FOUNDRY_MODEL": "model"},
            "toolboxes": {"caldova-skills": {"version": "3"}},
            "skills": {"caldova-orchard": {"version": "2", "marker": "secret-marker"}},
            "agents": {},
        }
        api.call.side_effect = [
            {"version": "13"},
            {"status": "completed", "output": [
                {"type": "message", "content": [{"text": "Skill unavailable"}]}]},
            {"status": "completed", "output": [
                {"type": "message", "content": [{"text": "Hello"}]}]},
        ]
        with patch("caldova.experiments.Foundry", return_value=api), \
                patch("caldova.experiments.save_state"), \
                patch("caldova.experiments.record") as record, patch("builtins.print"):
            run_discovery("caldova-skills")
        inspection, greeting = [call.args[1] for call in record.call_args_list]
        self.assertEqual(inspection["status"], "FAIL")
        self.assertEqual(greeting["status"], "PASS")
        self.assertEqual(inspection["agent_version"], "13")
        self.assertEqual(greeting["loading_mechanism"], "INDETERMINATE")
        self.assertEqual(inspection["project_endpoint"], api.endpoint)
        self.assertEqual(greeting["project_endpoint"], api.endpoint)

    def test_refetch_does_not_pass_retention_check(self):
        markers = expected_markers(1024, "test-run")
        for refetch in (False, True):
            with self.subTest(refetch=refetch):
                api = Mock()
                api.endpoint = "https://example.test/project"
                api.state = {"agents": {"caldova-prompt": {"version": "7"}}}
                followup_output = [{"type": "message", "content": [{"text": markers["END"]}]}]
                if refetch:
                    followup_output.append({"type": "mcp_call", "name": "large_result"})
                api.call.side_effect = [
                    {"id": "response", "status": "completed", "output": [
                        {"type": "message", "content": [{"text": "\n".join(
                            [markers["BEGIN"], markers["MIDDLE"]])}]}]},
                    {"status": "completed", "output": followup_output},
                ]
                with patch("caldova.experiments.Foundry", return_value=api), \
                        patch("caldova.experiments.uuid.uuid4", return_value=SimpleNamespace(hex="test-run")), \
                        patch("caldova.experiments.record") as record:
                    run_spill([1024])
                assessment = record.call_args.args[1]
                self.assertEqual(assessment["refetched_payload"], refetch)
                self.assertEqual(assessment["answer_correct"], not refetch)


class StatePathTests(unittest.TestCase):
    @staticmethod
    def _state(endpoint: str) -> dict:
        return {"tenant": "tenant", "outputs": {"FOUNDRY_PROJECT_ENDPOINT": endpoint, "FOUNDRY_MODEL": "model"}}

    def test_state_round_trip_uses_supplied_path_only(self):
        with tempfile.TemporaryDirectory() as directory:
            secondary = Path(directory) / "second" / "lab.json"
            secondary.parent.mkdir()
            with patch.object(cloud, "STATE", Path(directory) / "must-not-exist.json"):
                cloud.save_state({"a": 1}, secondary)
                self.assertEqual(cloud.load_state(secondary), {"a": 1})
            self.assertFalse((Path(directory) / "must-not-exist.json").exists())
            self.assertEqual([item.name for item in secondary.parent.iterdir()], ["lab.json"])

    def test_secondary_agent_creation_does_not_clobber_primary_and_records_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            primary, secondary = Path(directory) / "primary.json", Path(directory) / "secondary.json"
            cloud.save_state({**self._state("https://east.test/api/projects/lab"),
                              "agents": {"caldova-prompt": {"version": "7"}}}, primary)
            cloud.save_state(self._state("https://central.test/api/projects/lab"), secondary)
            primary_before = primary.read_text()
            client = Mock()
            definitions = {}

            def respond(method, url, json=None, headers=None):
                agent = url.split("/agents/")[1].split("/")[0]
                if method == "POST":
                    definitions[agent] = json["definition"]
                return Mock(is_error=False, status_code=200, json=Mock(
                    return_value={"version": "1", "definition": definitions[agent]}))

            client.request.side_effect = respond
            with patch("caldova.experiments.token", return_value="credential"), \
                    patch("caldova.experiments.httpx.Client", return_value=client), \
                    patch("caldova.experiments.record") as record:
                create_agents(state_path=secondary)
            self.assertEqual(primary.read_text(), primary_before)
            saved = cloud.load_state(secondary)
            self.assertEqual(set(saved["agents"]), {"caldova-prompt", "caldova-copilot"})
            urls = [call.args[1] for call in client.request.call_args_list]
            self.assertTrue(urls and all(url.startswith("https://central.test/") for url in urls))
            for call in record.call_args_list:
                self.assertEqual(call.args[1]["project_endpoint"], "https://central.test/api/projects/lab")
                self.assertNotIn("credential", json.dumps(call.args[1]))

    def test_default_foundry_reads_default_state(self):
        with patch("caldova.experiments.load_state", return_value=self._state("https://east.test")) as load, \
                patch("caldova.experiments.token", return_value="credential"):
            api = Foundry()
            api.close()
        load.assert_called_once_with(Path(".azure/lab.json"))
        self.assertEqual(api.state_path, Path(".azure/lab.json"))

    def test_inspect_cli_validates_toolbox_against_supplied_state(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "second.json"
            cloud.save_state({**self._state("https://central.test"), "toolboxes": {"known": {"version": "1"}}}, state)
            result = subprocess.run(
                [sys.executable, "-m", "caldova.inspect_mcp", "missing", "--state", str(state)],
                check=False, capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown toolbox", result.stderr)
        self.assertIn("second.json", result.stderr)

    def test_nondefault_state_is_rejected_for_identity_and_outputs(self):
        import subprocess
        import sys
        for operation in ("identity", "outputs"):
            result = subprocess.run(
                [sys.executable, "-m", "caldova.cloud", operation, "--state", "other.json"],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("only for authorize", result.stderr)

if __name__ == "__main__":
    unittest.main()
