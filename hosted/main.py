"""Isolated hosted experiments. UI adaptation is explicit; offloading is not implemented here."""

import asyncio
import base64
import hashlib
import importlib.metadata
import json
import logging
import os
import re
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from azure.ai.agentserver.responses import ResponsesAgentServerHost, TextResponse
from azure.identity.aio import DefaultAzureCredential
from copilot import CopilotClient, PermissionHandler, define_tool
from copilot.session import PermissionDecisionUserNotAvailable
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, ConfigDict, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("caldova.hosted")
lock = asyncio.Lock()
UI_URI = "ui://caldova/table"
MARKERS = re.compile(r"(BEGIN|MIDDLE|END)=([0-9a-f]{24})")


class WidgetParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")


class Invocation(WidgetParams):
    operation: Literal["smoke", "auth", "catalog", "resource", "widget", "offload", "native_apps", "native_rpc"]
    native_route: Literal["direct", "toolbox"] = "direct"
    rpc_method: Literal["tools/list", "tools/call", "resources/list", "resources/read"] = "tools/list"
    rpc_tool: str | None = None
    rpc_uri: str | None = None
    rpc_arguments: dict = Field(default_factory=dict)
    size_bytes: int = Field(default=65536, ge=1024, le=1048576)
    uri: Literal["ui://caldova/table"] = UI_URI


@asynccontextmanager
async def mcp_session(credential, *, source: bool = False):
    scope = os.environ["MCP_AUDIENCE"] + "/.default" if source else "https://ai.azure.com/.default"
    access = await credential.get_token(scope)
    url = os.environ["MCP_ENDPOINT" if source else "TOOLBOX_ENDPOINT"]
    async with (
        streamablehttp_client(url, headers={"Authorization": "Bearer " + access.token}) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        yield session


def permission(request, invocation):
    allowed = False
    if request.kind == "read":
        path = Path(request.path).resolve()
        allowed = path.is_relative_to(Path(tempfile.gettempdir()).resolve())
    elif request.kind == "mcp":
        allowed = request.server_name == "lab" and request.tool_name == "caldova___large_result"
    elif request.kind == "custom-tool":
        allowed = request.tool_name == "show_table"
    if allowed:
        return PermissionHandler.approve_all(request, invocation)
    logger.warning("Rejected experimental runtime permission: %s", request.kind)
    return PermissionDecisionUserNotAvailable()


def output_files():
    """Inspect only runtime output candidates, never credential/configuration files."""
    roots = [Path(tempfile.gettempdir()), Path.home() / "caldova-copilot"]
    files = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if (path.is_symlink() or not path.is_file()
                    or path.suffix not in {".txt", ".log"}
                    or not any(word in path.name.lower() for word in ("copilot", "tool", "output"))):
                continue
            stat = path.stat()
            files[str(path)] = (stat.st_size, stat.st_mtime_ns)
    return files


def matching_files(before, expected):
    matches = []
    for filename, state in output_files().items():
        if before.get(filename) == state or state[0] > 4 * 1024 * 1024:
            continue
        content = Path(filename).read_bytes()
        found = dict(MARKERS.findall(content.decode("utf-8", errors="replace")))
        if found == expected:
            matches.append({
                "path": filename, "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(), "markers": found,
            })
    return matches


def record(path, value):
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(value) + "\n")
        file.flush()
        os.fsync(file.fileno())


async def run_agent(data, credential):
    evidence_dir = Path.home() / "caldova-evidence"
    evidence_dir.mkdir(exist_ok=True)
    evidence_path = evidence_dir / f"{data.run_id}-{uuid.uuid4().hex}.jsonl"
    runtime_base = Path.home() / "caldova-copilot"
    work = Path.home() / "caldova-work"
    work.mkdir(exist_ok=True)
    result = {
        "operation": data.operation, "run_id": data.run_id,
        "platform_session_id": os.environ.get("FOUNDRY_AGENT_SESSION_ID"),
        "copilot_sdk_version": importlib.metadata.version("github-copilot-sdk"),
        "large_output_configuration": "SDK/runtime default; no override supplied",
        "evidence_path": str(evidence_path),
        "events": [],
    }
    record(evidence_path, {"phase": "started", **result})

    async def bearer(_args):
        return (await credential.get_token("https://ai.azure.com/.default")).token

    client = CopilotClient(base_directory=str(runtime_base), working_directory=str(work))
    captured = []

    @define_tool(name="show_table", description="Display the synthetic MCP App table.", defer="never")
    async def show_table(params: WidgetParams):
        if params.run_id != data.run_id:
            raise ValueError("The model changed the experiment run ID")
        async with mcp_session(credential) as remote:
            response = await remote.call_tool("caldova___show_table", {"run_id": params.run_id})
        if response.isError:
            raise RuntimeError(response.model_dump_json())
        raw = response.model_dump(mode="json", by_alias=True, exclude_none=True)
        captured.append(raw)
        record(evidence_path, {"phase": "widget_tool_result", "result": raw})
        return response.model_dump_json(by_alias=True, exclude_none=True)

    def event_handler(event):
        name = event.type.value
        if name in {
            "tool.execution_start", "tool.execution_complete", "assistant.message",
            "assistant.usage", "session.error",
        }:
            value = event.to_dict()
            result["events"].append(value)
            record(evidence_path, {"phase": "runtime_event", "event": value})

    options = {
        "on_permission_request": permission,
        "model": os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
        "provider": {
            "type": "openai", "base_url": os.environ["PROJECT_ENDPOINT"] + "/openai/v1",
            "wire_api": "responses", "bearer_token_provider": bearer,
        },
        "working_directory": str(work),
        "skip_custom_instructions": True,
        "enable_config_discovery": False,
        "enable_host_git_operations": False,
        "on_event": event_handler,
    }
    if data.operation == "widget":
        options["tools"] = [show_table]
        prompt = f"Call show_table exactly once with run_id {data.run_id}. Then reply briefly."
    elif data.operation == "offload":
        access = await credential.get_token("https://ai.azure.com/.default")
        options["mcp_servers"] = {"lab": {
            "type": "http", "url": os.environ["TOOLBOX_ENDPOINT"],
            "headers": {"Authorization": "Bearer " + access.token},
            "tools": ["caldova___large_result"],
        }}
        prompt = (
            f"Call caldova___large_result exactly once with size_bytes={data.size_bytes} "
            f"and run_id={data.run_id}. Return only its exact BEGIN and MIDDLE marker values. "
            "If the runtime gives you a file reference, use read-only file tools. "
            "Do not create, write, or modify any file yourself."
        )
    else:
        prompt = "Reply exactly HOSTED_COPILOT_READY without using tools."
    before = output_files()
    try:
        await client.start()
        session = await client.create_session(**options)
        result["copilot_session_id"] = session.session_id
        first = await session.send_and_wait(prompt, timeout=180)
        result["answer"] = first.data.content if first else None
        if data.operation == "widget":
            if len(captured) != 1:
                raise RuntimeError(f"Expected one actual Toolbox call; observed {len(captured)}")
            result["tool_result"] = captured[0]
            result["tool_execution_path"] = "Hosted Copilot SDK custom tool -> Foundry Toolbox -> MCP"
        elif data.operation == "offload":
            expected = {
                label: hashlib.sha256(f"{data.run_id}:{data.size_bytes}:{label}".encode()).hexdigest()[:24]
                for label in ("BEGIN", "MIDDLE", "END")
            }
            result["expected_markers"] = expected
            result["runtime_output_files"] = matching_files(before, expected)
            record(evidence_path, {"phase": "first_turn_complete", **result})
            followup = await session.send_and_wait(
                "Without calling the MCP tool again and without writing files, return only the "
                "exact END marker value from that earlier result. You may read its existing file.",
                timeout=120,
            )
            result["followup_answer"] = followup.data.content if followup else None
        record(evidence_path, {"phase": "completed", **result})
        await session.disconnect()
        return result
    finally:
        await client.stop()


async def execute(data):
    async with lock, DefaultAzureCredential(exclude_interactive_browser_credential=True) as credential:
        if data.operation == "native_apps":
            from native_apps import probe
            return await probe(data, credential, record)
        if data.operation == "native_rpc":
            from native_apps import rpc
            return await rpc(data, credential)
        if data.operation == "auth":
            access = await credential.get_token("https://ai.azure.com/.default")
            segment = access.token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.post(
                    os.environ["PROJECT_ENDPOINT"] + "/openai/v1/responses",
                    headers={"Authorization": "Bearer " + access.token},
                    json={"model": os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
                          "input": "Reply exactly AUTH_OK.", "max_output_tokens": 256},
                )
            return {
                "credential_claims": {key: claims.get(key) for key in ("aud", "iss", "oid", "appid", "azp")},
                "direct_model_status": response.status_code,
                "direct_model_body": response.json(),
            }
        if data.operation == "catalog":
            async with mcp_session(credential) as remote:
                tools = await remote.list_tools()
            tool = next(tool for tool in tools.tools if tool.name == "caldova___show_table")
            descriptor = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
            descriptor["name"] = "show_table"
            descriptor["_meta"] = {"ui": tool.meta["ui"]}
            async with mcp_session(credential, source=True) as remote:
                resources = await remote.list_resources()
            return {
                "tools": [descriptor],
                "resources": [resource.model_dump(mode="json", by_alias=True, exclude_none=True)
                              for resource in resources.resources if str(resource.uri) == UI_URI],
                "resource_path": "Explicit authenticated bridge to source MCP; not Toolbox forwarding",
            }
        if data.operation == "resource":
            async with mcp_session(credential, source=True) as remote:
                resource = await remote.read_resource(data.uri)
            return resource.model_dump(mode="json", by_alias=True, exclude_none=True)
        return await run_agent(data, credential)


async def respond(request, context, _cancellation_signal):
    text = await context.get_input_text() or ""
    if not text.lstrip().startswith("{"):
        from channel import respond as channel_response

        async def events():
            async with lock, DefaultAzureCredential(exclude_interactive_browser_credential=True) as credential:
                async for event in channel_response(text, request, context, credential, record):
                    yield event

        return events()
    data = Invocation.model_validate_json(text)
    result = await execute(data)
    return TextResponse(context, request, text=json.dumps(result))


if __name__ == "__main__":
    app = ResponsesAgentServerHost()
    app.response_handler(respond)
    app.run()
