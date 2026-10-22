"""Synthetic MCP server with Entra bearer-token validation."""

import asyncio
import hashlib
import json
import logging
import os
from collections import OrderedDict
from pathlib import Path

import jwt
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse

from caldova.fixtures import DOMAINS, payload, validate_run_id

logger = logging.getLogger("caldova")


class EntraVerifier:
    def __init__(self, tenant: str, audience: str):
        self.issuer = f"https://login.microsoftonline.com/{tenant}/v2.0"
        self.audience = audience
        self.keys = jwt.PyJWKClient(f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys")

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            key = await asyncio.to_thread(self.keys.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token, key.key, algorithms=["RS256"], audience=self.audience,
                issuer=self.issuer, options={"require": ["exp", "aud", "iss", "sub"]},
            )
            scopes = claims.get("scp", "").split()
            if "Mcp.Invoke" in claims.get("roles", []):
                scopes.append("Mcp.Access")
            if "Mcp.Access" not in scopes:
                logger.warning("auth_rejected: required scope/role missing")
                return None
            return AccessToken(
                token=token, client_id=claims.get("azp", ""),
                subject=claims["sub"], scopes=scopes, expires_at=claims["exp"],
            )
        except jwt.PyJWTError as error:
            logger.warning("auth_rejected: %s", type(error).__name__)
            return None


def build_server(*, local: bool = False) -> FastMCP:
    tenant = os.environ.get("MCP_TENANT_ID", "")
    audience = os.environ.get("MCP_AUDIENCE", "")
    resource = os.environ.get("MCP_RESOURCE_URL", "")
    if not local and not all((tenant, audience, resource)):
        raise ValueError("MCP_TENANT_ID, MCP_AUDIENCE and MCP_RESOURCE_URL are required")
    auth = None if local else AuthSettings(
        issuer_url=AnyHttpUrl(f"https://login.microsoftonline.com/{tenant}/v2.0"),
        resource_server_url=AnyHttpUrl(resource),
        required_scopes=["Mcp.Access"],
        validate_token_resource=False,
    )
    server = FastMCP(
        "Caldova synthetic fixtures", host="127.0.0.1" if local else "0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        stateless_http=True, json_response=True,
        token_verifier=None if local else EntraVerifier(tenant, audience),
        auth=auth,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*"] if local else [
                AnyHttpUrl(resource).host, "localhost:*", "127.0.0.1:*",
            ],
        ),
    )
    readonly = ToolAnnotations(readOnlyHint=True, destructiveHint=False)

    def audit(method: str, name: str, run_id: str = "", **details: object) -> None:
        logger.warning(json.dumps({"method": method, "name": name, "run_id": run_id, **details}))

    def register_catalog(domain: str) -> None:
        def lookup(run_id: str) -> str:
            validate_run_id(run_id)
            audit("tools/call", f"lookup_{domain}", run_id)
            return json.dumps({"domain": domain, "fixture_value": f"{domain}-verified", "run_id": run_id})
        server.add_tool(
            lookup, name=f"lookup_{domain}",
            description=f"Retrieve the synthetic verification record for {domain}.",
            annotations=readonly, structured_output=False,
        )

    for domain in DOMAINS:
        register_catalog(domain)

    @server.tool(annotations=readonly, structured_output=False)
    def large_result(size_bytes: int, run_id: str) -> str:
        """Return raw synthetic records containing BEGIN, MIDDLE and END values. No files are created."""
        text = payload(size_bytes, run_id)
        audit("tools/call", "large_result", run_id, size_bytes=len(text),
              sha256=hashlib.sha256(text.encode()).hexdigest())
        return text

    counters: OrderedDict[str, int] = OrderedDict()

    @server.tool(
        annotations=readonly,
        meta={"ui": {"resourceUri": "ui://caldova/table"}},
    )
    def show_table(run_id: str) -> CallToolResult:
        """Display an interactive synthetic table. Refresh calls this tool and increments its display counter."""
        validate_run_id(run_id)
        counters[run_id] = counters.get(run_id, 0) + 1
        counters.move_to_end(run_id)
        while len(counters) > 256:
            counters.popitem(last=False)
        data = {"run_id": run_id, "counter": counters[run_id], "rows": [
            {"name": "Synthetic orchard", "value": 42}, {"name": "Synthetic harbor", "value": 17},
        ]}
        audit("tools/call", "show_table", run_id, counter=data["counter"])
        return CallToolResult(
            content=[TextContent(type="text", text=f"Caldova table, refresh counter {data['counter']}.")],
            structuredContent=data,
        )

    @server.resource(
        "ui://caldova/table", mime_type="text/html;profile=mcp-app",
        meta={"ui": {"csp": {"resourceDomains": ["https://esm.sh"], "connectDomains": []}}},
    )
    def ui() -> str:
        audit("resources/read", "ui://caldova/table")
        return Path(__file__).with_name("widget.html").read_text(encoding="utf-8")

    @server.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "fixture": "caldova"})

    return server


if __name__ == "__main__":
    build_server().run(transport="streamable-http")
