"""Personal-scope publishing; generated packages and identifiers stay ignored."""

import argparse
import io
import json
import os
import struct
import uuid
import zlib
from pathlib import Path
from urllib.parse import urlparse
from zipfile import ZipFile

import httpx

from caldova.cloud import az, load_state, request, token
from caldova.experiments import record

STATE = Path(".azure/m365-state.json")
RESOURCE = "https://ai.azure.com"


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)


def agent(state: dict) -> dict:
    endpoint = state["outputs"]["FOUNDRY_PROJECT_ENDPOINT"]
    return request("GET", f"{endpoint}/agents/caldova-prompt?api-version=v1",
                   state["tenant"], RESOURCE)


def icon(size: int, outline: bool = False) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            border = (size // 4 <= x < 3 * size // 4 and size // 4 <= y < 3 * size // 4
                      and min(x - size // 4, y - size // 4,
                              3 * size // 4 - 1 - x, 3 * size // 4 - 1 - y) < max(1, size // 12))
            rows.extend((255, 255, 255, 255) if border else
                        ((0, 0, 0, 0) if outline else (23, 50, 77, 255)))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def control_documents(app_id: str, auth_config_id: str, mcp_url: str) -> dict:
    uuid.UUID(app_id)
    if not auth_config_id.strip() or "${" in auth_config_id:
        raise ValueError("A real OAuthPluginVault registration ID is required")
    parsed = urlparse(mcp_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("MCP_URL must be an HTTPS endpoint without embedded credentials")
    values = {"CONTROL_APP_ID": app_id, "AUTH_CONFIG_ID": auth_config_id, "MCP_URL": mcp_url}
    # Escape replacements as JSON string contents, not source-code fragments.
    escaped = {key: json.dumps(value)[1:-1] for key, value in values.items()}
    documents = {}
    for name in ("manifest.json", "declarativeAgent.json", "ai-plugin.json"):
        text = (Path("m365") / name).read_text()
        for key, value in escaped.items():
            text = text.replace("${" + key + "}", value)
        if "${" in text:
            raise ValueError(f"Unresolved template input in {name}")
        documents[name] = json.loads(text)
    return documents


def package_control(publication: dict) -> None:
    auth_id = os.environ["CALDOVA_AUTH_CONFIG_ID"]
    app_id = publication.get("control_app_id", str(uuid.uuid4()))
    documents = control_documents(app_id, auth_id, os.environ["CALDOVA_MCP_URL"])
    target = Path(".azure/control-app.zip")
    target.parent.mkdir(exist_ok=True)
    with ZipFile(target, "w") as archive:
        for name, document in documents.items():
            archive.writestr(name, json.dumps(document, indent=2))
        archive.writestr("color.png", icon(192))
        archive.writestr("outline.png", icon(32, outline=True))
    with ZipFile(target) as archive:
        if json.loads(archive.read("ai-plugin.json")) != documents["ai-plugin.json"]:
            raise RuntimeError("Packaged plugin differs from the requested configuration")
    publication.update(control_app_id=app_id, auth_config_id=auth_id)
    save(STATE, publication)
    print("Control package created privately; not registered, installed, or UI-verified.")


def provision_bot(state: dict, publication: dict) -> None:
    current = agent(state)
    identity = current["instance_identity"]["client_id"]
    endpoint = (state["outputs"]["FOUNDRY_PROJECT_ENDPOINT"].rstrip("/")
                + "/agents/caldova-prompt/endpoint/protocols/activityProtocol?api-version=2025-05-15-preview")
    parameters = [
        f"agentClientId={identity}", f"tenantId={state['tenant']}",
        f"messagingEndpoint={endpoint}",
    ]
    provider = az("provider", "show", "--namespace", "Microsoft.BotService",
                  "--subscription", state["subscription"])
    if provider["registrationState"] != "Registered":
        az("provider", "register", "--namespace", "Microsoft.BotService",
           "--subscription", state["subscription"], "--wait")
    arguments = [
        "--subscription", state["subscription"], "--resource-group", "rg-caldova-demo",
        "--template-file", "infra/bot.bicep", "--parameters", *parameters,
    ]
    preview = az("deployment", "group", "what-if", "--no-pretty-print", *arguments)
    save(Path("evidence/m365-bot-what-if.json"), preview)
    allowed = (
        f"/subscriptions/{state['subscription']}/resourceGroups/rg-caldova-demo"
        "/providers/Microsoft.BotService/botServices/caldova-prompt-bot"
    ).lower()
    for change in preview.get("changes", []):
        if change["changeType"] != "Ignore" and not (
            change["resourceId"].lower() == allowed
            or change["resourceId"].lower() == f"{allowed}/channels/msteamschannel"
        ):
            raise RuntimeError("Bot deployment proposed a change outside its two-resource scope")
    result = az("deployment", "group", "create", "--name", "caldova-channel-bot", *arguments)
    readback = az("bot", "show", "--subscription", state["subscription"],
                  "--resource-group", "rg-caldova-demo", "--name", "caldova-prompt-bot")
    record("m365-bot-endpoint-readback", readback)
    if readback["properties"]["endpoint"] != endpoint or readback["properties"]["msaAppId"] != identity:
        raise RuntimeError("Bot messaging endpoint or agent identity differs from the requested configuration")
    publication["bot_resource_id"] = result["properties"]["outputs"]["botResourceId"]["value"]
    publication["agent_client_id"] = identity
    save(STATE, publication)
    print("Lab-only Bot Service and Teams channel provisioned.")


def publish(state: dict, publication: dict, expected_version: str) -> None:
    current = agent(state)
    save(Path("evidence/m365-agent-before.json"), current)
    if current.get("versions", {}).get("latest", {}).get("version") != expected_version:
        raise RuntimeError("Agent latest version differs from expected version; inspect readback before publishing")
    if current["instance_identity"]["client_id"] != publication["agent_client_id"]:
        raise RuntimeError("Agent identity changed; reprovision the bot before publishing")
    selector = {"version_selection_rules": [
        {"type": "FixedRatio", "agent_version": expected_version, "traffic_percentage": 100},
    ]}
    endpoint = state["outputs"]["FOUNDRY_PROJECT_ENDPOINT"]
    request("PATCH", f"{endpoint}/agents/caldova-prompt?api-version=v1", state["tenant"], RESOURCE,
            headers={"Content-Type": "application/merge-patch+json"},
            json={"agent_endpoint": {"version_selector": selector}})
    pinned = agent(state)
    save(Path("evidence/m365-agent-pinned.json"), pinned)
    if pinned["agent_endpoint"]["version_selector"] != selector:
        raise RuntimeError("Published endpoint did not retain the requested pinned version")
    for key in ("protocol_configuration", "authorization_schemes"):
        if pinned["agent_endpoint"][key] != current["agent_endpoint"][key]:
            raise RuntimeError(f"Pinning unexpectedly changed {key}")
    body = {
        "agentDisplayName": "Caldova Prompt Lab",
        "botServiceArmId": publication["bot_resource_id"],
        "publishScope": "Shared", "publishAsAutopilot": False,
        "appVersion": "1.0.0",
        "shortDescription": "Synthetic Foundry capability lab",
        "fullDescription": "Personal test of tools, skills, large results, and interactive MCP fixtures.",
        "developerName": "Caldova",
        "developerWebsiteUrl": "https://github.com/ericchansen/caldova",
        "privacyUrl": "https://privacy.microsoft.com",
        "termsOfUseUrl": "https://www.microsoft.com/legal/terms-of-use",
    }
    base = f"{state['outputs']['FOUNDRY_PROJECT_ENDPOINT']}/agents/caldova-prompt/microsoft365"
    with httpx.Client(timeout=120, headers={
        "Authorization": f"Bearer {token(RESOURCE, state['tenant'])}",
    }) as client:
        response = client.post(f"{base}/zip?api-version=v1", json=body)
        if response.is_error:
            save(Path("evidence/m365-package-error.json"),
                 {"status": response.status_code, "body": response.text})
        response.raise_for_status()
        with ZipFile(io.BytesIO(response.content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        if manifest["bots"][0]["botId"] != publication["agent_client_id"]:
            raise RuntimeError("Generated manifest points at a different bot")
        Path(".azure/foundry-app.zip").write_bytes(response.content)
        save(Path("evidence/m365-foundry-manifest.json"), manifest)
        result = client.post(f"{base}/publish?api-version=v1", json=body)
        save(Path("evidence/m365-publish-response.json"),
             {"status": result.status_code, "body": result.text})
        result.raise_for_status()
        publication["publish_response"] = result.json()
        publication["expected_version"] = expected_version
        publication["scope"] = "Shared"
        save(STATE, publication)
    after = agent(state)
    save(Path("evidence/m365-agent-after.json"), after)
    if after["agent_endpoint"]["version_selector"] != selector:
        raise RuntimeError("Publication changed the pinned agent version")
    schemes = {item["type"] for item in after["agent_endpoint"]["authorization_schemes"]}
    if not {"Entra", "BotServiceRbac"} <= schemes or "BotServiceTenant" in schemes:
        raise RuntimeError("Publication did not preserve personal/RBAC authorization")
    print("Personal publication accepted; rendering still requires separate Copilot and Teams evidence.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["bot", "publish", "control-package"])
    parser.add_argument("--expected-version")
    args = parser.parse_args()
    state = load_state()
    publication = json.loads(STATE.read_text()) if STATE.exists() else {}
    if args.operation == "bot":
        provision_bot(state, publication)
    elif args.operation == "control-package":
        package_control(publication)
    elif not args.expected_version:
        parser.error("publish requires --expected-version from verified agent readback")
    else:
        publish(state, publication, args.expected_version)


if __name__ == "__main__":
    main()
