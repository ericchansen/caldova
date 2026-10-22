import copy
import os
import struct
import unittest
from unittest.mock import patch

from caldova.publish import configure_control_sso, control_documents, icon, provision_bot, publish


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

    def test_pinned_diagnostic_retains_discovered_ui_metadata_and_auth(self):
        tool = {"name": "show_table", "description": "Fixture", "inputSchema": {"type": "object"},
                "_meta": {"ui": {"resourceUri": "ui://caldova/table"}}}
        docs = control_documents("12345678-1234-4234-8234-123456789012",
                                 "registration", "https://fixture.example/mcp", tool)
        runtime = docs["ai-plugin.json"]["runtimes"][0]
        self.assertEqual(runtime["run_for_functions"], ["show_table"])
        self.assertEqual(runtime["spec"]["mcp_tool_description"]["tools"][0]["_meta"], tool["_meta"])
        self.assertEqual(runtime["auth"], {"type": "OAuthPluginVault", "reference_id": "registration"})
        self.assertEqual(docs["manifest.json"]["version"], "1.0.1")
        with self.assertRaises(ValueError):
            control_documents("12345678-1234-4234-8234-123456789012",
                              "registration", "https://fixture.example/mcp", {**tool, "name": "other"})

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

    def test_sso_preserves_existing_permissions_and_accepts_server_reordering(self):
        app = {
            "identifierUris": ["api://fixture-app"],
            "api": {
                "requestedAccessTokenVersion": 2,
                "oauth2PermissionScopes": [{"id": "scope", "value": "Mcp.Access", "isEnabled": True}],
                "preAuthorizedApplications": [{"appId": "existing-client", "delegatedPermissionIds": ["scope"]}],
            },
            "web": {"redirectUris": ["https://fixture.example/redirect"]},
            "appRoles": [{"id": "existing-role", "value": "Mcp.Invoke"}],
        }
        original = copy.deepcopy(app)

        def graph(method, *args, **kwargs):
            if method == "PATCH":
                app.update(copy.deepcopy(kwargs["json"]))
                app["api"]["preAuthorizedApplications"].reverse()
                return {}
            return copy.deepcopy(app)

        with patch.dict(os.environ, {
            "CALDOVA_SSO_APP_URI": "api://auth-registration/fixture-app",
            "CALDOVA_AUTH_CONFIG_ID": "registration",
        }), patch("caldova.publish.request", side_effect=graph), patch("caldova.publish.save"), \
                patch("caldova.publish.record"):
            state = {"mcp_app_id": "fixture-app", "mcp_application_object_id": "fixture-object", "tenant": "tenant"}
            configure_control_sso(state, {})
            self.assertEqual(app["appRoles"], original["appRoles"])
            self.assertEqual(app["api"]["oauth2PermissionScopes"], original["api"]["oauth2PermissionScopes"])
            self.assertIn(original["api"]["preAuthorizedApplications"][0], app["api"]["preAuthorizedApplications"])
            self.assertIn("api://fixture-app", app["identifierUris"])
            self.assertIn("https://fixture.example/redirect", app["web"]["redirectUris"])


if __name__ == "__main__":
    unittest.main()
