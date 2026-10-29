"""Authenticated remote MCP facade; tool calls execute model turns in Foundry."""

import asyncio
import json
import logging
import os

import httpx
from azure.identity import ManagedIdentityCredential
from mcp import types
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse

from caldova.server import EntraVerifier

logger = logging.getLogger("caldova.facade")
catalog_snapshot = {}
RESOURCE = os.environ["MCP_RESOURCE_URL"]
HOSTED = os.environ["HOSTED_PROJECT_ENDPOINT"] + "/agents/caldova-hosted-capabilities/endpoint"
server = FastMCP(
    "Caldova Foundry-backed MCP", host="0.0.0.0", port=8000,
    stateless_http=True, json_response=True,
    token_verifier=EntraVerifier(os.environ["MCP_TENANT_ID"], os.environ["MCP_AUDIENCE"]),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(f"https://login.microsoftonline.com/{os.environ['MCP_TENANT_ID']}/v2.0"),
        resource_server_url=AnyHttpUrl(RESOURCE), required_scopes=["Mcp.Access"],
        validate_token_resource=False,
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[AnyHttpUrl(RESOURCE).host, "localhost:*", "127.0.0.1:*"],
    ),
)


async def invoke(method, **fields):
    with ManagedIdentityCredential(client_id=os.environ["AZURE_CLIENT_ID"]) as credential:
        access = await asyncio.to_thread(credential.get_token, "https://ai.azure.com/.default")
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                HOSTED + "/protocols/openai/responses?api-version=v1",
                headers={"Authorization": "Bearer " + access.token},
                json={"input": json.dumps({
                    "operation": "delegated_rpc", "run_id": "remote-facade",
                    "native_route": "direct", "rpc_method": method, **fields,
                }), "stream": False},
            )
    logger.warning(json.dumps({"method": method, "status": response.status_code, **fields}))
    response.raise_for_status()
    body = response.json()
    if body.get("status") != "completed":
        raise RuntimeError("Hosted execution did not complete")
    text = "".join(
        part["text"] for item in body["output"] if item["type"] == "message"
        for part in item["content"] if part["type"] == "output_text"
    )
    result = json.loads(text)
    logger.warning(json.dumps({"method": method, "phase": "completed",
                               "structuredContent": result.get("structuredContent")}))
    return result


@server._mcp_server.list_tools()
async def list_tools():
    result = catalog_snapshot.get("tools/list")
    if result is None:
        result = await invoke("tools/list")
    return [types.Tool.model_validate(tool) for tool in result["tools"]]


@server._mcp_server.call_tool()
async def call_tool(name, arguments):
    return types.CallToolResult.model_validate(
        await invoke("tools/call", rpc_tool=name, rpc_arguments=arguments)
    )


@server._mcp_server.list_resources()
async def list_resources():
    result = catalog_snapshot.get("resources/list")
    if result is None:
        result = await invoke("resources/list")
    return [types.Resource.model_validate(item) for item in result["resources"]]


@server._mcp_server.read_resource()
async def read_resource(uri):
    result = await invoke("resources/read", rpc_uri=str(uri))
    return [ReadResourceContents(content=item["text"], mime_type=item["mimeType"], meta=item.get("_meta"))
            for item in result["contents"]]


@server.custom_route("/health", methods=["GET"])
async def health(_: Request):
    return JSONResponse({"status": "ok", "service": "foundry-backed-mcp"})


if __name__ == "__main__":
    # M365 discovery timed out while waiting for a cold hosted SDK session.
    # Refresh this lab catalog snapshot on startup, before accepting traffic.
    async def preload():
        for method in ("tools/list", "resources/list"):
            catalog_snapshot[method] = await invoke(method)

    asyncio.run(preload())
    server.run(transport="streamable-http")
