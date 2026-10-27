"""Loopback transport for the reference host; all operations run in the hosted agent."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route

from caldova.cloud import load_state, token
from caldova.experiments import record
from caldova.fixtures import validate_run_id

MODE = os.environ.get("CALDOVA_UI_PATH", "custom")
if MODE not in {"custom", "native-direct", "native-toolbox"}:
    raise ValueError("CALDOVA_UI_PATH must be custom, native-direct or native-toolbox")
PORT = int(os.environ.get("CALDOVA_UI_PORT", "8082"))
server = Server(
    "Foundry hosted agent with explicit MCP Apps bridge" if MODE == "custom"
    else f"Foundry hosted native SDK ({MODE.removeprefix('native-')} MCP)"
)
STATE = Path(os.environ.get("CALDOVA_HOSTED_STATE", ".azure/hosted-centralus-state.json"))


async def invoke(operation, *, session_id=None, **fields):
    state = load_state()
    hosted = json.loads(STATE.read_text())
    region = load_state(Path(".azure/harness-region.json"))
    if (hosted["name"] != "caldova-hosted-capabilities"
            or hosted["project_endpoint"] not in {
                state["outputs"]["FOUNDRY_PROJECT_ENDPOINT"],
                region["outputs"]["FOUNDRY_PROJECT_ENDPOINT"],
            }):
        raise ValueError("Hosted state does not identify this lab's experiment")
    access = await asyncio.to_thread(token, "https://ai.azure.com", state["tenant"])
    selected_session = session_id or hosted.get("test_session_id")
    url = hosted["project_endpoint"] + f"/agents/{hosted['name']}/endpoint/protocols/openai/responses"
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            url, params={"api-version": "v1"},
            headers={"Authorization": "Bearer " + access},
            json={
                "input": json.dumps({"operation": operation, "run_id": "hosted-ui-catalog", **fields}),
                "stream": False,
                **({"agent_session_id": selected_session} if selected_session else {}),
            },
        )
    record(f"hosted-frontend-{operation}", {
        "at": datetime.now(UTC).isoformat(),
        "project_endpoint": hosted["project_endpoint"], "version": hosted["version"],
        "agent_session_id": selected_session,
        "status": response.status_code, "body": response.text,
    })
    response.raise_for_status()
    body = response.json()
    if body.get("status") != "completed":
        raise RuntimeError(f"Hosted response did not complete: {body}")
    text = "".join(
        part["text"] for item in body.get("output", []) if item.get("type") == "message"
        for part in item.get("content", []) if part.get("type") == "output_text"
    )
    return json.loads(text)


@server.list_tools()
async def list_tools():
    if MODE != "custom":
        result = await invoke("native_rpc", native_route=MODE.removeprefix("native-"), rpc_method="tools/list")
        return [types.Tool.model_validate(tool) for tool in result["tools"]]
    result = await invoke("catalog")
    return [types.Tool.model_validate(tool) for tool in result["tools"]]


@server.list_resources()
async def list_resources():
    if MODE != "custom":
        result = await invoke("native_rpc", native_route=MODE.removeprefix("native-"),
                              rpc_method="resources/list")
        return [types.Resource.model_validate(resource) for resource in result["resources"]]
    result = await invoke("catalog")
    return [types.Resource.model_validate(resource) for resource in result["resources"]]


@server.call_tool()
async def call_tool(name, arguments):
    if MODE != "custom":
        result = await invoke("native_rpc", native_route=MODE.removeprefix("native-"),
                              rpc_method="tools/call", rpc_tool=name, rpc_arguments=arguments)
        return types.CallToolResult.model_validate(result)
    if name != "show_table" or set(arguments) != {"run_id"}:
        raise ValueError("Only the synthetic widget tool is exposed")
    run_id = validate_run_id(arguments["run_id"])
    result = await invoke("widget", run_id=run_id)
    return types.CallToolResult.model_validate(result["tool_result"])


@server.read_resource()
async def read_resource(uri):
    if MODE != "custom":
        result = await invoke("native_rpc", native_route=MODE.removeprefix("native-"),
                              rpc_method="resources/read", rpc_uri=str(uri))
        return [
            ReadResourceContents(content=content["text"], mime_type=content["mimeType"],
                                 meta=content.get("_meta"))
            for content in result["contents"]
        ]
    if str(uri) != "ui://caldova/table":
        raise ValueError("Only the synthetic widget resource is exposed")
    result = await invoke("resource", uri=str(uri))
    return [
        ReadResourceContents(
            content=content["text"], mime_type=content["mimeType"], meta=content.get("_meta"),
        )
        for content in result["contents"]
    ]


manager = StreamableHTTPSessionManager(
    server, stateless=True, json_response=True,
    security_settings=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"127.0.0.1:{PORT}", f"localhost:{PORT}"],
        allowed_origins=["http://localhost:8080"],
    ),
)


class Endpoint:
    async def __call__(self, scope, receive, send):
        await manager.handle_request(scope, receive, send)


@asynccontextmanager
async def lifespan(_app):
    async with manager.run():
        yield


if __name__ == "__main__":
    application = Starlette(routes=[Route("/mcp", Endpoint())], lifespan=lifespan)
    application = CORSMiddleware(
        application, allow_origins=["http://localhost:8080"],
        allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"],
        expose_headers=["Mcp-Session-Id"],
    )
    uvicorn.run(application, host="127.0.0.1", port=PORT)
