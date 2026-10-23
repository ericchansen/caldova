"""Inspect the actual MCP protocol surface independently of an LLM."""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

import httpx
from mcp import ClientSession, McpError
from mcp.client.streamable_http import streamablehttp_client

from caldova.cloud import STATE, load_state, token
from caldova.experiments import record


async def inspect(name: str, read_ui: bool = False, *, state_path: Path = STATE) -> None:
    state = load_state(state_path)
    endpoint = state["outputs"]["FOUNDRY_PROJECT_ENDPOINT"]
    if name == "direct":
        url = state["outputs"]["MCP_ENDPOINT"]
        audience = f"api://{state['mcp_app_id']}"
        async with httpx.AsyncClient(timeout=60) as client:
            denied = await client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        record("mcp-direct-auth-rejection", {"project_endpoint": endpoint, "mcp_url": url,
                                            "status": denied.status_code})
        if denied.status_code != 401:
            raise RuntimeError(f"Expected authentication rejection; got HTTP {denied.status_code}")
    else:
        if name not in state.get("toolboxes", {}):
            raise SystemExit(f"Unknown Toolbox {name!r} in {state_path}")
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
            "project_endpoint": endpoint, "mcp_url": url,
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
                "project_endpoint": endpoint, "mcp_url": url,
                "first": first.model_dump(mode="json", by_alias=True),
                "second": second.model_dump(mode="json", by_alias=True),
            })
            if first.isError or second.isError or second.structuredContent["counter"] != 2:
                raise RuntimeError("Synthetic widget counter round-trip failed")
        if read_ui:
            try:
                ui = await session.read_resource("ui://caldova/table")
                record(f"mcp-{name}-ui-resource", {"project_endpoint": endpoint, "mcp_url": url, "status": "PASS",
                                                 "result": ui.model_dump(mode="json", by_alias=True)})
            except McpError as error:
                record(f"mcp-{name}-ui-resource", {
                    "project_endpoint": endpoint, "mcp_url": url, "status": "FAIL", "error": str(error),
                })
                raise
        if name.endswith("-search"):
            if not {"tool_search", "call_tool"} <= {tool.name for tool in tools.tools}:
                raise RuntimeError("Toolbox search meta-tools are missing")
            query = "Microsoft Foundry documentation" if "learn" in name else "orchards"
            result = await session.call_tool("tool_search", {"query": query, "limit": 2})
            record(f"mcp-{name}-search", {
                **result.model_dump(mode="json", by_alias=True), "project_endpoint": endpoint, "mcp_url": url,
            })
            if result.isError:
                raise RuntimeError(f"Tool search failed: {result.content}")
            print(str(result)[:2000])
        if name == "caldova-skills":
            discovery = resources.model_dump_json()
            if any(skill["marker"] in discovery for skill in state["skills"].values()):
                raise RuntimeError("Skill body markers leaked into resource discovery metadata")
            for index, resource in enumerate(resources.resources):
                result = await session.read_resource(resource.uri)
                record(f"mcp-{name}-resource-{index}", {
                    **result.model_dump(mode="json", by_alias=True), "project_endpoint": endpoint, "mcp_url": url,
                })
                for skill_name, skill in state["skills"].items():
                    if (str(resource.uri) == f"skill://{skill_name}/SKILL.md"
                            and skill["marker"] not in result.model_dump_json()):
                        raise RuntimeError(f"Missing expected marker in {skill_name}")
                print(f"Read {resource.uri}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("toolbox")
    parser.add_argument("--state", type=Path, default=STATE, help="Lab state file for the target Foundry project")
    parser.add_argument("--read-ui", action="store_true", help="Probe the resource URI advertised by show_table")
    args = parser.parse_args()
    if args.toolbox != "direct" and args.toolbox not in load_state(args.state).get("toolboxes", {}):
        parser.error(f"unknown toolbox {args.toolbox!r} in {args.state}")
    asyncio.run(inspect(args.toolbox, args.read_ui, state_path=args.state))
