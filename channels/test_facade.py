import importlib
import os
import unittest
from unittest.mock import AsyncMock, patch


class FacadeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            "MCP_RESOURCE_URL": "https://facade.test/mcp",
            "HOSTED_PROJECT_ENDPOINT": "https://foundry.test/api/projects/lab",
            "MCP_TENANT_ID": "test", "MCP_AUDIENCE": "test",
        }):
            cls.facade = importlib.import_module("channels.facade")

    async def test_preserves_discovered_tool_ui_metadata(self):
        tool = {"name": "table", "inputSchema": {"type": "object"},
                "_meta": {"ui": {"resourceUri": "ui://test/table"}}}
        with patch.object(self.facade, "invoke", AsyncMock(return_value={"tools": [tool]})):
            result = await self.facade.list_tools()
        self.assertEqual(result[0].meta, tool["_meta"])

    async def test_catalog_snapshot_avoids_a_cold_hosted_call_during_discovery(self):
        tool = {"name": "table", "inputSchema": {"type": "object"}}
        with patch.dict(self.facade.catalog_snapshot, {"tools/list": {"tools": [tool]}}), patch.object(
            self.facade, "invoke", AsyncMock()
        ) as invoke:
            result = await self.facade.list_tools()
        self.assertEqual(result[0].name, "table")
        invoke.assert_not_awaited()

    async def test_preserves_result_and_resource_without_direct_source_fallback(self):
        invoke = AsyncMock(return_value={"content": [], "structuredContent": {"counter": 2}, "isError": False})
        with patch.object(self.facade, "invoke", invoke):
            result = await self.facade.call_tool("table", {"run_id": "test"})
        invoke.assert_awaited_once_with("tools/call", rpc_tool="table", rpc_arguments={"run_id": "test"})
        self.assertEqual(result.structuredContent, {"counter": 2})
        content = {"text": "<html>Test</html>", "mimeType": "text/html;profile=mcp-app",
                   "_meta": {"ui": {"csp": {"connectDomains": []}}}}
        with patch.object(self.facade, "invoke", AsyncMock(return_value={"contents": [content]})):
            resource = await self.facade.read_resource("ui://test/table")
        self.assertEqual(resource[0].content, content["text"])
        self.assertEqual(resource[0].meta, content["_meta"])
