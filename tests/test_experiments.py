import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from caldova.experiments import Foundry, native_skill_diagnostic, run_discovery, run_spill
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

    def test_refetch_does_not_pass_retention_check(self):
        markers = expected_markers(1024, "test-run")
        for refetch in (False, True):
            with self.subTest(refetch=refetch):
                api = Mock()
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


if __name__ == "__main__":
    unittest.main()
