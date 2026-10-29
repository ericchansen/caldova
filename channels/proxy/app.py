"""Authenticated Activity -> existing Foundry Responses text proxy.

Intentionally no invented MCP Apps attachment or declarative plugin.
"""
import json
import logging
import os
import uuid
from urllib.parse import quote, urlsplit

import httpx
from aiohttp import web
from azure.identity.aio import ManagedIdentityCredential
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import (
    CloudAdapter,
    jwt_authorization_middleware,
    start_agent_process,
)
from microsoft_agents.hosting.core import AgentApplication, AgentAuthConfiguration, MemoryStorage
from microsoft_agents.hosting.core.authorization import AuthTypes

LOG = logging.getLogger("caldova.proxy")


def channel_diagnostic(activity, tenant_id):
    """Log channel shape after JWT validation, never message/user/token payloads."""
    data = activity.channel_data if isinstance(activity.channel_data, dict) else {}
    tenant = data.get("tenant")
    channel_tenant = tenant.get("id") if isinstance(tenant, dict) else None
    conversation = activity.conversation
    conversation_tenant = conversation.tenant_id if conversation else None
    return {
        "event": "proxy_channel_received",
        "channel": activity.channel_id,
        "activity_id": activity.id,
        "conversation_type": conversation.conversation_type if conversation else None,
        "is_group": conversation.is_group if conversation else None,
        "channel_tenant_present": bool(channel_tenant),
        "channel_tenant_matches": channel_tenant == tenant_id,
        "conversation_tenant_present": bool(conversation_tenant),
        "conversation_tenant_matches": conversation_tenant == tenant_id,
    }


def response_text(body):
    if body.get("status") != "completed":
        raise ValueError("Foundry response was not completed")
    text = "\n".join(
        part["text"] for item in body.get("output", []) if item.get("type") == "message"
        for part in item.get("content", []) if part.get("type") == "output_text"
    )
    if not text:
        raise ValueError("Foundry returned no output_text")
    return text


class Foundry:
    def __init__(self, credential, project_endpoint, agent_name):
        parsed = urlsplit(project_endpoint)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Configure an HTTPS Foundry project endpoint")
        if not agent_name:
            raise ValueError("Configure a hosted agent name")
        self.credential = credential
        self.endpoint = (
            f"{project_endpoint.rstrip('/')}/agents/{quote(agent_name, safe='')}"
            "/endpoint/protocols/openai/responses"
        )

    async def invoke(self, text):
        access = await self.credential.get_token("https://ai.azure.com/.default")
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                self.endpoint,
                params={"api-version": "v1"},
                headers={"Authorization": f"Bearer {access.token}"},
                json={"input": text, "stream": False},
            )
        response.raise_for_status()
        body = response.json()
        LOG.info(json.dumps({
            "event": "foundry_completed", "response_id": body.get("id"),
            "output_types": [x.get("type") for x in body.get("output", [])],
            "mcp_call_count": sum(x.get("type") == "mcp_call" for x in body.get("output", [])),
        }))
        return response_text(body)


def create_app(client_id, tenant_id, backend):
    # Fail closed; never fall back to SDK's anonymous quickstart.
    uuid.UUID(client_id)
    uuid.UUID(tenant_id)
    auth = AgentAuthConfiguration(
        auth_type=AuthTypes.user_managed_identity, client_id=client_id,
        tenant_id=tenant_id, anonymous_allowed=False, validate_issuer=True,
        scopes=["https://api.botframework.com/.default"],
    )
    manager = MsalConnectionManager({"SERVICE_CONNECTION": auth})
    adapter = CloudAdapter(connection_manager=manager)
    agent = AgentApplication(storage=MemoryStorage(), connection_manager=manager)

    @agent.activity("message")
    async def message(context, _state):
        activity = context.activity
        LOG.info(json.dumps(channel_diagnostic(activity, tenant_id)))
        # Teams messages must be personal and from this tenant. Direct Line is
        # an authenticated, secret-protected lab smoke route on this new bot.
        if activity.channel_id == "msteams":
            data = activity.channel_data or {}
            if (data.get("tenant", {}).get("id") != tenant_id
                    or activity.conversation.conversation_type != "personal"):
                await context.send_activity("This lab accepts personal-scope messages in its own tenant only.")
                return
        elif activity.channel_id != "directline":
            await context.send_activity("This lab channel is not enabled.")
            return
        text = (activity.text or "").strip()
        # Do not expose the hosted experiment's JSON RPC dispatcher as chat.
        if not text or len(text) > 8000 or text.startswith(("{", "[")):
            await context.send_activity("Send a natural-language lab prompt (1–8000 characters), not JSON.")
            return
        correlation = str(uuid.uuid4())
        LOG.info(json.dumps({"event": "proxy_turn", "correlation": correlation,
                             "channel": activity.channel_id, "activity_id": activity.id}))
        try:
            result = await backend.invoke(text)
            await context.send_activity(result[:24000])
        except Exception as exc:  # noqa: BLE001 -- channel boundary: redact failures, return correlation only.
            LOG.error(json.dumps({"event": "proxy_error", "correlation": correlation,
                                  "error_type": type(exc).__name__}))
            await context.send_activity(f"Proxy invocation failed. Reference: {correlation}")

    async def entry(request):
        return await start_agent_process(request, agent, adapter)

    app = web.Application(middlewares=[jwt_authorization_middleware])
    app["agent_configuration"] = auth
    app["agent_app"] = agent
    app["adapter"] = adapter
    app.router.add_post("/api/messages", entry)
    # No anonymous diagnostic/invocation endpoint. Container uses TCP probes.
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    client_id = os.environ["PROXY_CLIENT_ID"]
    credential = ManagedIdentityCredential(client_id=client_id)
    backend = Foundry(credential, os.environ["PROXY_PROJECT_ENDPOINT"], os.environ["PROXY_AGENT_NAME"])
    app = create_app(client_id, os.environ["PROXY_TENANT_ID"], backend)

    async def cleanup(_app):
        await credential.close()

    app.on_cleanup.append(cleanup)
    web.run_app(app, host="0.0.0.0", port=3978)
