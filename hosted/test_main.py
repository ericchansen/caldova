import importlib.util
import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError

SPEC = importlib.util.spec_from_file_location(
    "hosted_main", Path(__file__).with_name("main.py")
)
hosted = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hosted)


class HostedBoundaryTests(unittest.TestCase):
    def test_only_bounded_fixture_requests_are_accepted(self):
        for invalid in (
            {"run_id": "../escape", "operation": "widget"},
            {"run_id": "test", "operation": "offload", "size_bytes": 1048577},
            {"run_id": "test", "operation": "resource", "uri": "file:///etc/passwd"},
            {"run_id": "test", "operation": "widget", "url": "https://example.com"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                hosted.Invocation.model_validate(invalid)

    def test_permissions_reject_writes_shell_and_unrelated_tools(self):
        for request in (
            SimpleNamespace(kind="write"),
            SimpleNamespace(kind="shell"),
            SimpleNamespace(kind="custom-tool", tool_name="delete"),
            SimpleNamespace(kind="mcp", server_name="other", tool_name="caldova___large_result"),
        ):
            self.assertIsInstance(hosted.permission(request, {}), hosted.PermissionDecisionUserNotAvailable)

    def test_file_evidence_requires_the_exact_payload_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "copilot-tool-output-test.txt"
            expected = {"BEGIN": "a" * 24, "MIDDLE": "b" * 24, "END": "c" * 24}
            path.write_text("\n".join(f"{key}={value}" for key, value in expected.items()))
            with patch.object(hosted, "output_files", return_value={str(path): (path.stat().st_size, 1)}):
                self.assertEqual(len(hosted.matching_files({}, expected)), 1)
                self.assertEqual(hosted.matching_files({}, {**expected, "END": "d" * 24}), [])
                self.assertEqual(hosted.matching_files({str(path): (path.stat().st_size, 1)}, expected), [])


class NativeRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import native_apps
        self.module = native_apps
        tools = [
            {"name": "first", "_meta": {"ui": {"resourceUri": "ui://sample/first"}}},
            {"name": "second", "_meta": {"ui": {"resourceUri": "ui://sample/second"}}},
            {"name": "ordinary"},
        ]
        self.apps = SimpleNamespace(
            list_tools=AsyncMock(return_value=SimpleNamespace(tools=tools)),
            call_tool=AsyncMock(return_value={"content": [], "structuredContent": {"value": 42}}),
            read_resource=AsyncMock(return_value=SimpleNamespace(to_dict=lambda: {"contents": []})),
        )
        session = SimpleNamespace(rpc=SimpleNamespace(mcp=SimpleNamespace(apps=self.apps)))

        @asynccontextmanager
        async def connected(*_args):
            yield None, session

        self.patcher = patch.object(native_apps, "connected_session", connected)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_dispatches_an_arbitrary_discovered_tool(self):
        data = hosted.Invocation(
            operation="native_rpc", run_id="test", rpc_method="tools/call",
            rpc_tool="second", rpc_arguments={"key": "value"},
        )
        result = await self.module.rpc(data, None)
        request = self.apps.call_tool.call_args.args[0]
        self.assertEqual(request.tool_name, "second")
        self.assertEqual(request.arguments, {"key": "value"})
        self.assertEqual(result["structuredContent"], {"value": 42})

    async def test_reads_the_discovered_uri_not_a_fixed_widget(self):
        data = hosted.Invocation(
            operation="native_rpc", run_id="test", rpc_method="resources/read",
            rpc_uri="ui://sample/second",
        )
        await self.module.rpc(data, None)
        self.assertEqual(self.apps.read_resource.call_args.args[0].uri, "ui://sample/second")

    async def test_rejects_unadvertised_tool_and_resource(self):
        for fields in (
            {"rpc_method": "tools/call", "rpc_tool": "unadvertised"},
            {"rpc_method": "resources/read", "rpc_uri": "file:///private"},
        ):
            with self.assertRaises(ValueError):
                await self.module.rpc(hosted.Invocation(operation="native_rpc", run_id="test", **fields), None)
        self.apps.call_tool.assert_not_called()
        self.apps.read_resource.assert_not_called()

    async def test_delegated_tool_requires_exact_model_call_and_returns_raw_result(self):
        @asynccontextmanager
        async def connected(_route, _credential, callback):
            async def send(*_args, **_kwargs):
                for kind, data in [
                    ("tool.execution_start", {"toolCallId": "a", "mcpToolName": "second",
                                              "arguments": {"key": "value"}}),
                    ("tool.execution_complete", {"toolCallId": "a", "success": True,
                                                 "result": {"contents": [], "structuredContent": {"counter": 2}}}),
                ]:
                    callback(SimpleNamespace(type=SimpleNamespace(value=kind),
                                             to_dict=lambda k=kind, d=data: {"type": k, "data": d}))
            yield None, SimpleNamespace(
                rpc=SimpleNamespace(mcp=SimpleNamespace(apps=self.apps)), send_and_wait=send,
            )
        with patch.object(self.module, "connected_session", connected):
            data = hosted.Invocation(operation="delegated_rpc", run_id="test", rpc_method="tools/call",
                                     rpc_tool="second", rpc_arguments={"key": "value"})
            result = await self.module.rpc(data, None)
        self.assertEqual(result["structuredContent"], {"counter": 2})
        self.apps.call_tool.assert_not_called()


class ChannelTests(unittest.TestCase):
    def test_channel_output_preserves_structured_result_and_ui_metadata(self):
        from channel import tool_output
        data = {
            "success": True,
            "result": {"contents": [{"type": "text", "text": "table"}],
                       "structuredContent": {"counter": 1}},
            "toolDescription": {"_meta": {"ui": {"resourceUri": "ui://sample/table"}}},
        }
        output = tool_output(data)
        self.assertEqual(output["structuredContent"], {"counter": 1})
        self.assertEqual(output["_meta"]["ui"]["resourceUri"], "ui://sample/table")
        self.assertFalse(output["isError"])
        self.assertTrue(tool_output({"success": False, "error": {"message": "failed"}})["isError"])


class ChannelStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_tool_items_and_answer_survive_response_stream(self):
        import channel
        from azure.ai.agentserver.responses._id_generator import IdGenerator
        tools = [{"name": "show_table", "inputSchema": {},
                  "_meta": {"ui": {"resourceUri": "ui://sample/table"}}}]

        @asynccontextmanager
        async def connected(_route, _credential, on_event):
            async def send(*_args, **_kwargs):
                for kind, data in (
                    ("tool.execution_start", {"toolCallId": "one", "mcpServerName": "fixture",
                                              "mcpToolName": "show_table", "arguments": {"run_id": "test"}}),
                    ("tool.execution_complete", {"toolCallId": "one", "success": True,
                                                 "result": {"contents": [], "structuredContent": {"counter": 1}}}),
                ):
                    event = {"type": kind, "data": data}
                    on_event(SimpleNamespace(type=SimpleNamespace(value=kind), to_dict=lambda e=event: e))
                return SimpleNamespace(data=SimpleNamespace(content="Table result"))

            yield None, SimpleNamespace(
                send_and_wait=send,
                rpc=SimpleNamespace(mcp=SimpleNamespace(apps=SimpleNamespace(
                    list_tools=AsyncMock(return_value=SimpleNamespace(tools=tools)),
                ))),
            )

        with tempfile.TemporaryDirectory() as directory, patch.object(
            channel, "connected_session", connected
        ), patch.object(channel.Path, "home", return_value=Path(directory)):
            events = [event async for event in channel.respond(
                "Display table", {}, SimpleNamespace(response_id=IdGenerator.new_response_id()),
                None, lambda *_args: None,
            )]
        response = events[-1]["response"]
        self.assertEqual(response["status"], "completed")
        described = response["output"][0]["tools"][0]
        self.assertEqual(described["input_schema"], {})
        self.assertNotIn("inputSchema", described)
        self.assertEqual(described["_meta"], tools[0]["_meta"])
        self.assertIn('"counter": 1', response["output"][1]["output"])
        self.assertEqual(response["output"][2]["content"][0]["text"], "Table result")


class HostedPublicationTests(unittest.TestCase):
    def test_deploy_preserves_existing_channel_protocols_and_auth(self):
        from hosted import deploy
        endpoint = "https://example.test/api/projects/lab"
        previous = {
            "protocol_configuration": {"responses": {}, "activity": {}},
            "authorization_schemes": [{"type": "Entra"}, {"type": "BotServiceRbac"}],
        }
        api = Mock(endpoint=endpoint, state={"outputs": {"FOUNDRY_MODEL": "test"}})
        api.client.get.return_value.json.return_value = {"agent_endpoint": previous}
        selector = {"version_selection_rules": [
            {"type": "FixedRatio", "agent_version": "7", "traffic_percentage": 100},
        ]}
        api.call.side_effect = [
            {"version": "7"}, {"status": "active"}, {},
            {"agent_endpoint": {**previous, "version_selector": selector}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hosted.json"
            path.write_text(json.dumps({"name": deploy.NAME, "project_endpoint": endpoint}))
            with patch.object(deploy, "Foundry", return_value=api), patch.object(
                deploy, "load_state", return_value={
                    "outputs": {"AZURE_CONTAINER_REGISTRY_ENDPOINT": "registry.test",
                                "MCP_ENDPOINT": "https://mcp.test/mcp"},
                    "mcp_app_id": "test",
                }
            ):
                deploy.deploy("registry.test/caldova-hosted@sha256:test", output_state=path)
        patch_call = next(call for call in api.call.call_args_list if call.args[0] == "PATCH")
        routed = patch_call.kwargs["body"]["agent_endpoint"]
        for key, value in previous.items():
            self.assertEqual(routed[key], value)


if __name__ == "__main__":
    unittest.main()
