import importlib.util
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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


if __name__ == "__main__":
    unittest.main()
