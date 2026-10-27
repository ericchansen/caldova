"""Probe SDK-native MCP Apps APIs without registering per-tool Python wrappers."""

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from copilot import CopilotClient, PermissionHandler
from copilot.generated.rpc import (
    MCPAppsCallToolRequest,
    MCPAppsDiagnoseRequest,
    MCPAppsListToolsRequest,
    MCPAppsReadResourceRequest,
    MCPIsServerRunningRequest,
    MCPResourcesListRequest,
    MCPStartServerRequest,
)
from copilot.session import PermissionDecisionUserNotAvailable

SERVER_NAME = "fixture"


@asynccontextmanager
async def connected_session(route, credential, on_event=None):
    direct = route == "direct"
    scope = os.environ["MCP_AUDIENCE"] + "/.default" if direct else "https://ai.azure.com/.default"
    access = await credential.get_token(scope)
    endpoint = os.environ["MCP_ENDPOINT" if direct else "TOOLBOX_ENDPOINT"]
    def permission(request, invocation):
        if request.kind == "mcp" and request.server_name == SERVER_NAME and request.read_only:
            return PermissionHandler.approve_all(request, invocation)
        return PermissionDecisionUserNotAvailable()

    async def bearer(_args):
        return (await credential.get_token("https://ai.azure.com/.default")).token

    client = CopilotClient(
        base_directory=str(Path.home() / "native-apps-copilot"),
        env={**os.environ, "COPILOT_MCP_APPS": "true"},
    )
    try:
        await client.start()
        session = await client.create_session(
            model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
            provider={
                "type": "openai", "base_url": os.environ["PROJECT_ENDPOINT"] + "/openai/v1",
                "wire_api": "responses", "bearer_token_provider": bearer,
            },
            on_permission_request=permission,
            on_event=on_event,
            enable_mcp_apps=True,
            enable_config_discovery=False,
            skip_custom_instructions=True,
            mcp_servers={SERVER_NAME: {
                "type": "http", "url": endpoint, "tools": ["*"],
                "headers": {"Authorization": "Bearer " + access.token},
            }},
        )
        running = await session.rpc.mcp.is_server_running(MCPIsServerRunningRequest(SERVER_NAME))
        if not running.running:
            await session.rpc.mcp.start_server(MCPStartServerRequest(SERVER_NAME))
        yield client, session
        await session.disconnect()
    finally:
        await client.stop()


async def rpc(data, credential):
    """Generic transport adapter: SDK native APIs own discovery, scoping and tool execution."""
    async with connected_session(data.native_route, credential) as (_, session):
        catalog = await session.rpc.mcp.apps.list_tools(
            MCPAppsListToolsRequest(origin_server_name=SERVER_NAME, server_name=SERVER_NAME)
        )
        if data.rpc_method == "tools/list":
            return catalog.to_dict()
        if data.rpc_method == "tools/call":
            if data.rpc_tool not in {tool["name"] for tool in catalog.tools}:
                raise ValueError("Tool is not app-callable in this server's native SDK catalog")
            return await session.rpc.mcp.apps.call_tool(MCPAppsCallToolRequest(
                origin_server_name=SERVER_NAME, server_name=SERVER_NAME,
                tool_name=data.rpc_tool, arguments=data.rpc_arguments,
            ))
        uris = {
            tool.get("_meta", {}).get("ui", {}).get("resourceUri") for tool in catalog.tools
        } - {None}
        if data.rpc_method == "resources/list":
            resources = await session.rpc.mcp.resources.list(MCPResourcesListRequest(SERVER_NAME))
            return {"resources": [
                resource for resource in resources.to_dict()["resources"] if resource["uri"] in uris
            ]}
        if data.rpc_uri not in uris:
            raise ValueError("Resource URI was not advertised by this server's app-callable tools")
        resource = await session.rpc.mcp.apps.read_resource(
            MCPAppsReadResourceRequest(SERVER_NAME, data.rpc_uri)
        )
        return resource.to_dict()


async def probe(data, credential, record):
    server_name = SERVER_NAME
    events = []
    evidence_dir = Path.home() / "caldova-evidence"
    evidence_dir.mkdir(exist_ok=True)
    evidence_path = evidence_dir / f"native-apps-{data.run_id}-{uuid.uuid4().hex}.jsonl"

    def on_event(event):
        if event.type.value in {"tool.execution_start", "tool.execution_complete", "assistant.message"}:
            events.append(event.to_dict())
            record(evidence_path, {"phase": "runtime_event", "event": event.to_dict()})

    async with connected_session(data.native_route, credential, on_event) as (client, session):
        status = await client.get_status()
        answer = await session.send_and_wait(
            f"Use the available MCP tools to look up orchards and display the interactive synthetic table. "
            f"Use run_id={data.run_id} for both calls. Call each needed tool once and reply briefly.",
            timeout=180,
        )
        diagnosis = await session.rpc.mcp.apps.diagnose(MCPAppsDiagnoseRequest(server_name))
        catalog = await session.rpc.mcp.apps.list_tools(
            MCPAppsListToolsRequest(origin_server_name=server_name, server_name=server_name)
        )
        ui_tools = [
            tool for tool in catalog.tools
            if tool.get("_meta", {}).get("ui", {}).get("resourceUri", "").startswith("ui://")
        ]
        if not ui_tools:
            raise RuntimeError("SDK native catalog exposed no MCP Apps tool")
        record(evidence_path, {
            "phase": "catalog",
            "runtime": status.to_dict(),
            "capabilities": session.capabilities,
            "diagnostic_capability": diagnosis.capability.to_dict(),
            "catalog_count": len(catalog.tools),
            "ui_tools": ui_tools,
        })
        tool = ui_tools[0]
        resource = await session.rpc.mcp.apps.read_resource(
            MCPAppsReadResourceRequest(server_name, tool["_meta"]["ui"]["resourceUri"])
        )
        refreshed = await session.rpc.mcp.apps.call_tool(MCPAppsCallToolRequest(
            origin_server_name=server_name, server_name=server_name,
            tool_name=tool["name"], arguments={"run_id": data.run_id},
        ))
        if refreshed.get("isError"):
            raise RuntimeError(f"Native MCP Apps tool callback failed: {refreshed}")
        result = {
            "route": data.native_route,
            "run_id": data.run_id,
            "platform_session_id": os.environ.get("FOUNDRY_AGENT_SESSION_ID"),
            "copilot_session_id": session.session_id,
            "runtime": status.to_dict(),
            "capabilities": session.capabilities,
            "diagnostic_capability": diagnosis.capability.to_dict(),
            "catalog_count": len(catalog.tools),
            "ui_tools": ui_tools,
            "resource": resource.to_dict(),
            "app_callback_result": refreshed,
            "answer": answer.data.content if answer else None,
            "events": events,
            "boundary": "Native SDK APIs tested; this operation does not render a browser iframe.",
        }
        record(evidence_path, {"phase": "completed", **result})
        return result
