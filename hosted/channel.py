"""Natural-language channel probe, preserving native MCP evidence in Responses items."""

import asyncio
import json
import logging
import uuid
from pathlib import Path

from azure.ai.agentserver.responses import ResponseEventStream
from azure.ai.agentserver.responses._id_generator import IdGenerator
from copilot.generated.rpc import MCPAppsListToolsRequest
from native_apps import SERVER_NAME, connected_session

logger = logging.getLogger("caldova.channel")


def tool_output(data):
    result = data.get("result") or {}
    output = {"content": result.get("contents", []), "isError": not data.get("success", False)}
    if "structuredContent" in result:
        output["structuredContent"] = result["structuredContent"]
    metadata = data.get("toolDescription", {}).get("_meta")
    if metadata:
        output["_meta"] = metadata
    if data.get("error"):
        output["error"] = data["error"]
    return output


async def respond(prompt, request, context, credential, record):
    stream = ResponseEventStream(response_id=context.response_id, request=request)
    yield stream.emit_created()
    yield stream.emit_in_progress()
    directory = Path.home() / "caldova-evidence"
    directory.mkdir(exist_ok=True)
    evidence = directory / f"channel-{uuid.uuid4().hex}.jsonl"
    record(evidence, {"phase": "channel_request", "response_id": context.response_id, "input": prompt})
    queue = asyncio.Queue()

    def on_event(event):
        if event.type.value in {"tool.execution_start", "tool.execution_complete", "session.error"}:
            data = event.to_dict()
            record(evidence, data)
            logger.info("channel_event %s", json.dumps(data))
            queue.put_nowait(data)

    async with connected_session("direct", credential, on_event) as (_, session):
        catalog = await session.rpc.mcp.apps.list_tools(
            MCPAppsListToolsRequest(origin_server_name=SERVER_NAME, server_name=SERVER_NAME)
        )
        item = {
            "id": IdGenerator.new_mcp_list_tools_item_id(context.response_id),
            "type": "mcp_list_tools", "server_label": SERVER_NAME,
            "tools": [
                {**{key: value for key, value in tool.items() if key != "inputSchema"},
                 "input_schema": tool["inputSchema"]}
                for tool in catalog.tools
            ],
        }
        builder = stream.add_output_item(item["id"])
        yield builder.emit_added({**item, "tools": []})
        yield builder.emit_done(item)

        async def run():
            try:
                return await session.send_and_wait(prompt, timeout=180)
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(run())
        calls = {}
        try:
            while (event := await queue.get()) is not None:
                data = event["data"]
                if event["type"] == "tool.execution_start" and data.get("mcpServerName") == SERVER_NAME:
                    call = stream.add_output_item_mcp_call(SERVER_NAME, data["mcpToolName"])
                    calls[data["toolCallId"]] = call
                    yield call.emit_added()
                    yield call.emit_in_progress()
                    yield call.emit_arguments_done(json.dumps(data["arguments"]))
                elif event["type"] == "tool.execution_complete" and data["toolCallId"] in calls:
                    call = calls.pop(data["toolCallId"])
                    yield call.emit_completed() if data["success"] else call.emit_failed()
                    yield call.emit_done(output=json.dumps(tool_output(data)))
            answer = await task
            if calls:
                raise RuntimeError("SDK turn ended with unfinished MCP tool calls")
            if answer is None or not answer.data.content:
                raise RuntimeError("SDK channel turn returned no answer")
            record(evidence, {"phase": "channel_completed", "answer": answer.data.content})
            for event in stream.output_item_message(answer.data.content):
                yield event
            yield stream.emit_completed()
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
