import struct
import unittest
from unittest.mock import patch

from caldova.publish import control_documents, icon, provision_bot, publish


class PackageTests(unittest.TestCase):
    def test_bot_passes_required_activity_version_to_bicep_and_checks_readback(self):
        endpoint = "https://fixture.example/api/projects/lab"
        expected = endpoint + "/agents/caldova-prompt/endpoint/protocols/activityProtocol?api-version=2025-05-15-preview"
        state = {"tenant": "tenant", "subscription": "subscription",
                 "outputs": {"FOUNDRY_PROJECT_ENDPOINT": endpoint + "/"}}
        with patch("caldova.publish.agent", return_value={"instance_identity": {"client_id": "agent"}}), \
                patch("caldova.publish.save"), patch("caldova.publish.record"), \
                patch("caldova.publish.az", side_effect=[
                    {"registrationState": "Registered"}, {"changes": []},
                    {"properties": {"outputs": {"botResourceId": {"value": "bot-resource"}}}},
                    {"properties": {"endpoint": expected, "msaAppId": "agent"}},
                ]) as cli:
            provision_bot(state, {})
            create_call = next(call for call in cli.call_args_list if call.args[:3] == ("deployment", "group", "create"))
            self.assertIn("messagingEndpoint=" + expected, create_call.args)

    def test_control_keeps_auth_and_dynamic_widget_discovery(self):
        docs = control_documents("12345678-1234-4234-8234-123456789012",
                                 'fixture"registration', "https://fixture.example/mcp")
        runtime = docs["ai-plugin.json"]["runtimes"][0]
        self.assertEqual(runtime["auth"],
                         {"type": "OAuthPluginVault", "reference_id": 'fixture"registration'})
        self.assertEqual(runtime["run_for_functions"], ["*"])
        self.assertEqual(runtime["spec"]["url"], "https://fixture.example/mcp")
        self.assertEqual(docs["manifest.json"]["copilotAgents"]["declarativeAgents"][0]["file"],
                         "declarativeAgent.json")

    def test_rejects_insecure_or_unresolved_control(self):
        for url, auth in [("http://fixture.example/mcp", "registered"),
                          ("https://user:secret@fixture.example/mcp", "registered"),
                          ("https://fixture.example/mcp", "${AUTH_CONFIG_ID}")]:
            with self.assertRaises(ValueError):
                control_documents("12345678-1234-4234-8234-123456789012", auth, url)

    def test_icons_have_required_dimensions(self):
        for size in (32, 192):
            data = icon(size, outline=size == 32)
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), (size, size))

    def test_publish_refuses_stale_version_before_remote_write(self):
        with patch("caldova.publish.agent", return_value={
            "versions": {"latest": {"version": "8"}},
        }), patch("caldova.publish.save"), patch("caldova.publish.request") as remote:
            with self.assertRaisesRegex(RuntimeError, "latest version differs"):
                publish({}, {}, "7")
            remote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
