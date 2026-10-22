"""Inspect the actual MCP protocol surface independently of an LLM."""

import argparse
import asyncio
import json
import uuid

import httpx
from mcp import ClientSession, McpError
from mcp.client.streamable_http import streamablehttp_client

from caldova.cloud import load_state, token
from caldova.experiments import record


async def inspect(name: str, read_ui: bool = False) -> None:
    state = load_state()
    endpoint = state["outputs"]["FOUNDRY_PROJECT_ENDPOINT"]
    if name == "direct":
        url = state["outputs"]["MCP_ENDPOINT"]
        audience = f"api://{state['mcp_app_id']}"
        async with httpx.AsyncClient(timeout=60) as client:
            denied = await client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        record("mcp-direct-auth-rejection", {"status": denied.status_code})
        if denied.status_code != 401:
            raise RuntimeError(f"Expected authentication rejection; got HTTP {denied.status_code}")
    else:
        version = state["toolboxes"][name]["version"]
        url = f"{endpoint}/toolboxes/{name}/versions/{version}/mcp?api-version=v1"
        audience = "https://ai.azure.com"
    headers = {
        "Authorization": f"Bearer {token(audience, state['tenant'])}",
        "Foundry-Features": "Skills=V1Preview",
    }
    async with (
        streamablehttp_client(url, headers=headers) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        initialized = await session.initialize()
        tools = await session.list_tools()
        resources = await session.list_resources()
        record(f"mcp-{name}-discovery", {
            "initialize": initialized.model_dump(mode="json", by_alias=True),
            "tools": tools.model_dump(mode="json", by_alias=True),
            "resources": resources.model_dump(mode="json", by_alias=True),
        })
        print(json.dumps({
            "tools": [tool.name for tool in tools.tools],
            "resources": [str(resource.uri) for resource in resources.resources],
        }, indent=2))
        if name == "direct":
            run_id = uuid.uuid4().hex
            first = await session.call_tool("show_table", {"run_id": run_id})
            second = await session.call_tool("show_table", {"run_id": run_id})
            record("mcp-direct-widget-roundtrip", {
                "first": first.model_dump(mode="json", by_alias=True),
                "second": second.model_dump(mode="json", by_alias=True),
            })
            if first.isError or second.isError or second.structuredContent["counter"] != 2:
                raise RuntimeError("Synthetic widget counter round-trip failed")
        if read_ui:
            try:
                ui = await session.read_resource("ui://caldova/table")
                record(f"mcp-{name}-ui-resource", {"status": "PASS",
                                                 "result": ui.model_dump(mode="json", by_alias=True)})
            except McpError as error:
                record(f"mcp-{name}-ui-resource", {"status": "FAIL", "error": str(error)})
                raise
        if name.endswith("-search"):
            if not {"tool_search", "call_tool"} <= {tool.name for tool in tools.tools}:
                raise RuntimeError("Toolbox search meta-tools are missing")
            query = "Microsoft Foundry documentation" if "learn" in name else "orchards"
            result = await session.call_tool("tool_search", {"query": query, "limit": 2})
            record(f"mcp-{name}-search", result.model_dump(mode="json", by_alias=True))
            if result.isError:
                raise RuntimeError(f"Tool search failed: {result.content}")
            print(str(result)[:2000])
        if name == "caldova-skills":
            discovery = resources.model_dump_json()
            if any(skill["marker"] in discovery for skill in state["skills"].values()):
                raise RuntimeError("Skill body markers leaked into resource discovery metadata")
            for index, resource in enumerate(resources.resources):
                result = await session.read_resource(resource.uri)
                record(f"mcp-{name}-resource-{index}", result.model_dump(mode="json", by_alias=True))
                for skill_name, skill in state["skills"].items():
                    if (str(resource.uri) == f"skill://{skill_name}/SKILL.md"
                            and skill["marker"] not in result.model_dump_json()):
                        raise RuntimeError(f"Missing expected marker in {skill_name}")
                print(f"Read {resource.uri}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("toolbox", choices=["direct", *load_state().get("toolboxes", {})])
    parser.add_argument("--read-ui", action="store_true", help="Probe the resource URI advertised by show_table")
    args = parser.parse_args()
    asyncio.run(inspect(args.toolbox, args.read_ui))
