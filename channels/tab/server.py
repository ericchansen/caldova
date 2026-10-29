"""Path6 only: Teams delegated-user auth -> managed identity -> hosted Foundry SDK."""
import asyncio
import hashlib
import html
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Annotated

import httpx
import jwt
from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError, ServiceResponseError
from azure.identity import ManagedIdentityCredential
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict

TENANT = os.environ.get("TAB_TENANT_ID", "")
APP_ID = os.environ.get("TAB_APP_ID", "")
HOST = os.environ.get("TAB_ORIGIN", "https://tab.example.invalid")
SANDBOX = os.environ.get("SANDBOX_ORIGIN", "https://sandbox.example.invalid")
MODE = os.environ.get("TAB_MODE", "host")
DIST = Path(__file__).parent / "dist"
UI_URI = "ui://caldova/table"
UI_MIME = "text/html;profile=mcp-app"
TEAMS_CLIENTS = {
    "1fec8e78-bce4-4aaf-ab1b-5451cc387264",  # Teams desktop/mobile
    "5e3ce6c0-2b1f-4285-8d4b-75ee78787346",  # Teams web
}
ALLOWED_CLIENTS = TEAMS_CLIENTS | set(filter(None, os.environ.get("TAB_DIAGNOSTIC_CLIENTS", "").split(",")))
ANCESTORS = "https://teams.microsoft.com https://*.teams.microsoft.com https://*.cloud.microsoft https://*.office.com https://*.microsoft365.com"
JWK = jwt.PyJWKClient(f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys", timeout=10)
logger = logging.getLogger("caldova.tab")
logging.basicConfig(level=logging.INFO)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
call_lock = asyncio.Lock()


def verify_user(token: str):
    """No anonymous fallback, cookies, app-only tokens, or other-resource tokens."""
    try:
        key = JWK.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key, algorithms=["RS256"], audience=APP_ID,
            issuer=f"https://login.microsoftonline.com/{TENANT}/v2.0",
            options={"require": ["exp", "iat", "nbf", "iss", "aud", "tid", "oid", "scp", "azp"]},
        )
        if claims["tid"] != TENANT or claims.get("ver") != "2.0":
            raise ValueError("Unexpected tenant or token version")
        if "access_as_user" not in claims["scp"].split() or claims["azp"] not in ALLOWED_CLIENTS:
            raise ValueError("Required scope or authorized client missing")
        uuid.UUID(claims["oid"])
        return claims
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(401, "Valid tab access_as_user user token required",
                            headers={"WWW-Authenticate": "Bearer"}) from exc


async def authenticated(request: Request):
    if MODE != "host":
        raise HTTPException(404)
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer ") or len(header) > 16384:
        raise HTTPException(401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"})
    if request.headers.get("origin") not in (None, HOST):
        raise HTTPException(403, "Unexpected request origin")
    return await asyncio.to_thread(verify_user, header[7:])


@app.middleware("http")
async def boundaries(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    if "Content-Security-Policy" not in response.headers:
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            f"connect-src 'self'; img-src 'self' data:; frame-src {SANDBOX}; "
            f"frame-ancestors {ANCESTORS}; object-src 'none'; base-uri 'none'; form-action 'none'"
        )
    return response


class Rpc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: str
    name: str | None = None
    uri: str | None = None
    arguments: dict | None = None

    def hosted_fields(self):
        if self.method == "tools/call":
            if self.name != "show_table" or self.uri is not None:
                raise HTTPException(403, "Only the synthetic App tool is allowed")
            if (not isinstance(self.arguments, dict) or set(self.arguments) != {"run_id"}
                    or not isinstance(self.arguments["run_id"], str)
                    or not re.fullmatch(r"tab-[a-zA-Z0-9_-]{1,60}", self.arguments["run_id"])):
                raise HTTPException(400, "Expected only a tab-prefixed synthetic run_id")
            return {"rpc_tool": self.name, "rpc_arguments": self.arguments}
        if self.method == "resources/read":
            if self.uri != UI_URI or self.name is not None or self.arguments is not None:
                raise HTTPException(403, "Only the advertised App resource is allowed")
            return {"rpc_uri": self.uri}
        if self.method not in {"tools/list", "resources/list"}:
            raise HTTPException(403, "Unsupported App operation")
        if self.name is not None or self.uri is not None or self.arguments is not None:
            raise HTTPException(400, "Unexpected parameters")
        return {}


async def invoke_hosted(method: str, request_id: str, fields: dict):
    endpoint = os.environ["HOSTED_PROJECT_ENDPOINT"].rstrip("/")
    endpoint += "/agents/caldova-hosted-capabilities/endpoint/protocols/openai/responses?api-version=v1"
    with ManagedIdentityCredential(client_id=os.environ["AZURE_CLIENT_ID"]) as credential:
        access = await asyncio.to_thread(credential.get_token, "https://ai.azure.com/.default")
        async with httpx.AsyncClient(timeout=190) as client:
            response = await client.post(endpoint, headers={"Authorization": "Bearer " + access.token}, json={
                "input": json.dumps({
                    "operation": "delegated_rpc", "native_route": "direct",
                    "run_id": request_id, "rpc_method": method, **fields,
                }), "stream": False,
            })
    response.raise_for_status()
    body = response.json()
    if body.get("status") != "completed":
        raise RuntimeError(f"Hosted response status {body.get('status')}")
    text = "".join(part["text"] for item in body["output"] if item["type"] == "message"
                   for part in item["content"] if part["type"] == "output_text")
    result = json.loads(text)
    if not isinstance(result, dict) or result.get("isError"):
        raise RuntimeError("Hosted SDK returned a tool error or invalid result")
    return result, body["id"]


def preserve_contract(method: str, result: dict):
    if method == "tools/list":
        tools = [tool for tool in result["tools"] if tool["name"] == "show_table"]
        if len(tools) != 1 or tools[0].get("_meta", {}).get("ui", {}).get("resourceUri") != UI_URI:
            raise RuntimeError("Hosted catalog lost the App resource contract")
        if "app" not in tools[0]["_meta"]["ui"].get("visibility", ["model", "app"]):
            raise RuntimeError("Source did not allow app visibility")
        return {**result, "tools": tools}
    if method == "resources/list":
        return {**result, "resources": [r for r in result["resources"] if r["uri"] == UI_URI]}
    if method == "resources/read":
        contents = result.get("contents", [])
        if len(contents) != 1 or contents[0].get("uri") != UI_URI or contents[0].get("mimeType") != UI_MIME:
            raise RuntimeError("Hosted resource URI or MIME type changed")
        if not isinstance(contents[0].get("text"), str):
            raise RuntimeError("Hosted resource HTML missing")
        ui = contents[0].get("_meta", {}).get("ui", {})
        validate_csp(ui.get("csp"))
        if ui.get("permissions"):
            raise RuntimeError("This bounded lab does not grant App device permissions")
    return result


@app.post("/api/rpc")
async def rpc(request: Request, claims: Annotated[dict, Depends(authenticated)]):
    if int(request.headers.get("content-length", "0")) > 4096:
        raise HTTPException(413, "Request too large")
    raw = await request.body()
    if len(raw) > 4096:
        raise HTTPException(413, "Request too large")
    try:
        data = Rpc.model_validate_json(raw)
    except ValueError as exc:
        raise HTTPException(400, "Invalid App request") from exc
    fields = data.hosted_fields()
    request_id = "tab-" + uuid.uuid4().hex
    # Serialized bounded synthetic operations; no arbitrary prompts, source URLs, or resource reads.
    if call_lock.locked():
        raise HTTPException(429, "Another App operation is in progress; retry shortly")
    try:
        async with call_lock:
            result, response_id = await invoke_hosted(data.method, request_id, fields)
        result = preserve_contract(data.method, result)
        logger.info(json.dumps({
            "request_id": request_id, "method": data.method, "phase": "completed",
            "user_hash": hashlib.sha256((TENANT + claims["oid"]).encode()).hexdigest()[:16],
            "hosted_response_id": response_id, "structuredContent": result.get("structuredContent"),
        }))
        return JSONResponse(result, headers={"X-Request-ID": request_id})
    except (
        httpx.HTTPError, ClientAuthenticationError, ServiceRequestError, ServiceResponseError,
        RuntimeError, ValueError, KeyError, TypeError,
    ) as exc:
        # No access tokens, full upstream request/response, or user claims in logs.
        upstream_status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        logger.error(json.dumps({"request_id": request_id, "method": data.method, "phase": "failed",
                                 "error_type": type(exc).__name__, "upstream_status": upstream_status}))
        return JSONResponse({"error": "Hosted operation failed; see tab logs", "request_id": request_id,
                             "error_type": type(exc).__name__, "upstream_status": upstream_status}, status_code=502)


def validate_csp(csp):
    if not isinstance(csp, dict) or csp.get("resourceDomains") != ["https://esm.sh"]:
        raise ValueError("Expected the source's pinned esm.sh resource domain")
    if set(csp) - {"resourceDomains", "connectDomains", "frameDomains", "baseUriDomains"}:
        raise ValueError("Unknown source CSP requirement")
    if any(csp.get(key) for key in ("connectDomains", "frameDomains", "baseUriDomains")):
        raise ValueError("This lab does not grant App network, frame, or base URI access")


@app.get("/sandbox.html")
async def sandbox(request: Request):
    if MODE != "sandbox":
        raise HTTPException(404)
    try:
        csp = json.loads(request.query_params.get("csp", "{}"))
        validate_csp(csp)
    except (ValueError, TypeError):
        raise HTTPException(400, "Unsupported source CSP")
    # Inject deployment configuration at serve time, never into publishable TS source.
    document = (DIST / "sandbox.html").read_text(encoding="utf-8")
    document = document.replace("__TAB_HOST_ORIGIN__", html.escape(HOST, quote=True))
    return HTMLResponse(document, headers={"Content-Security-Policy": (
        "default-src 'none'; script-src 'self' 'unsafe-inline' https://esm.sh; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'none'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; "
        f"frame-ancestors {HOST} {ANCESTORS}"
    )})


@app.get("/health")
async def health():
    return {"status": "ok", "mode": MODE}


@app.get("/config")
async def config():
    if MODE != "host":
        raise HTTPException(404)
    # Public app configuration only; no data, token or credential.
    return {"sandboxOrigin": SANDBOX, "appId": APP_ID, "tenantId": TENANT}


@app.get("/assets/{name}")
async def asset(name: str):
    allowed = ("sandbox-", "modulepreload-") if MODE == "sandbox" else ("host-", "modulepreload-")
    if not name.startswith(allowed) or not re.fullmatch(r"[\w.-]+\.(js|css)", name):
        raise HTTPException(404)
    path = DIST / "assets" / name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/")
@app.get("/index.html")
async def index():
    if MODE != "host":
        raise HTTPException(404)
    return FileResponse(DIST / "index.html")


@app.get("/privacy")
@app.get("/terms")
async def legal():
    return PlainTextResponse(
        "Caldova isolated synthetic lab. Tenant-authenticated users only. "
        "No real customer data, email, or production use. Logs contain synthetic results, "
        "request correlation IDs, and a pseudonymous user hash. Lab operators can delete resources and logs."
    )
