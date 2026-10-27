"""Publish only the isolated hosted experiment with personal/RBAC channel access."""

import argparse
import io
import json
from pathlib import Path
from zipfile import ZipFile

import httpx

from caldova.cloud import az, load_state, request, token
from caldova.experiments import record
from caldova.publish import save

NAME = "caldova-hosted-capabilities"
BOT = "caldova-hosted-bot"
TITLE = "Caldova Hosted Lab"
STATE = Path(".azure/hosted-m365-state.json")
RESOURCE = "https://ai.azure.com"


def publish():
    if STATE.exists():
        raise RuntimeError("Publication state already exists; inspect it rather than submitting again")
    lab = load_state()
    hosted = json.loads(Path(".azure/hosted-centralus-state.json").read_text())
    if hosted["name"] != NAME:
        raise ValueError("Unexpected hosted agent")
    endpoint = hosted["project_endpoint"]
    agent_url = endpoint + f"/agents/{NAME}?api-version=v1"
    before = request("GET", agent_url, lab["tenant"], RESOURCE)
    record("hosted-channel-publication-before", before)
    rules = before["agent_endpoint"]["version_selector"]["version_selection_rules"]
    if rules != [{"type": "FixedRatio", "agent_version": hosted["version"], "traffic_percentage": 100}]:
        raise RuntimeError("Hosted endpoint is not pinned to the tested version")
    if before["agent_endpoint"].get("publish_approval_status") != "not_published":
        raise RuntimeError("Hosted agent already has publication state; inspect before proceeding")
    identity = before["instance_identity"]["client_id"]
    messaging = endpoint + f"/agents/{NAME}/endpoint/protocols/activityProtocol?api-version=2025-05-15-preview"
    bot_id = (f"/subscriptions/{lab['subscription']}/resourceGroups/rg-caldova-demo"
              f"/providers/Microsoft.BotService/botServices/{BOT}")
    args = [
        "--subscription", lab["subscription"], "--resource-group", "rg-caldova-demo",
        "--template-file", "infra/bot.bicep", "--parameters",
        f"botName={BOT}", f"displayName={TITLE}", f"agentClientId={identity}",
        f"tenantId={lab['tenant']}", f"messagingEndpoint={messaging}",
    ]
    preview = az("deployment", "group", "what-if", "--no-pretty-print", *args)
    record("hosted-channel-bot-what-if", preview)
    allowed = {bot_id.lower(), (bot_id + "/channels/MsTeamsChannel").lower()}
    for change in preview.get("changes", []):
        if change["changeType"] != "Ignore" and (
            change["resourceId"].lower() not in allowed or change["changeType"] == "Delete"
        ):
            raise RuntimeError("Bot deployment exceeds the hosted experiment's scope")
    az("deployment", "group", "create", "--name", "caldova-hosted-channel", *args)
    bot = az("bot", "show", "--subscription", lab["subscription"],
             "--resource-group", "rg-caldova-demo", "--name", BOT)
    record("hosted-channel-bot-readback", bot)
    if bot["properties"]["endpoint"] != messaging or bot["properties"]["msaAppId"] != identity:
        raise RuntimeError("Hosted bot endpoint/identity mismatch")
    body = {
        "agentDisplayName": TITLE, "botServiceArmId": bot_id, "publishScope": "Shared",
        "publishAsAutopilot": False, "appVersion": "1.0.0",
        "shortDescription": "Synthetic hosted MCP Apps channel test",
        "fullDescription": "Personal lab for a Foundry-hosted Copilot SDK agent and authenticated synthetic MCP.",
        "developerName": "Caldova", "developerWebsiteUrl": "https://github.com/ericchansen/caldova",
        "privacyUrl": "https://privacy.microsoft.com",
        "termsOfUseUrl": "https://www.microsoft.com/legal/terms-of-use",
    }
    state = {"name": NAME, "version": hosted["version"], "project_endpoint": endpoint,
             "bot_resource_id": bot_id, "agent_client_id": identity, "request": body}
    base = endpoint + f"/agents/{NAME}/microsoft365"
    with httpx.Client(timeout=120, headers={"Authorization": "Bearer " + token(RESOURCE, lab["tenant"])}) as client:
        package = client.post(base + "/zip?api-version=v1", json=body)
        if package.is_error:
            record("hosted-channel-package-error", {"status": package.status_code, "body": package.text})
        package.raise_for_status()
        with ZipFile(io.BytesIO(package.content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        if manifest["bots"][0]["botId"] != identity:
            raise RuntimeError("Hosted manifest targets a different agent")
        Path(".azure/hosted-foundry-app.zip").write_bytes(package.content)
        record("hosted-channel-manifest", manifest)
        state["manifest"] = manifest
        save(STATE, state)
        result = client.post(base + "/publish?api-version=v1", json=body)
        record("hosted-channel-publish-response", {"status": result.status_code, "body": result.text})
        state["publish_status"] = result.status_code
        state["publish_body"] = result.text
        save(STATE, state)
        result.raise_for_status()
    after = request("GET", agent_url, lab["tenant"], RESOURCE)
    record("hosted-channel-publication-after", after)
    state["readback"] = after
    save(STATE, state)
    configuration = after["agent_endpoint"]
    schemes = {item["type"] for item in configuration["authorization_schemes"]}
    if (configuration["version_selector"] != before["agent_endpoint"]["version_selector"]
            or not {"responses", "activity"} <= set(configuration["protocol_configuration"])
            or not {"Entra", "BotServiceRbac"} <= schemes or "BotServiceTenant" in schemes):
        raise RuntimeError("Hosted publication changed the expected version or authentication")
    print("Hosted personal publication accepted; actual channel rendering still needs verification.")


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    publish()
