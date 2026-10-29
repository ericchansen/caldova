"""Create only the isolated tab SSO registration and its scoped MI. Never prints tokens."""
import json
import subprocess
import uuid
from pathlib import Path

import httpx
from azure.identity import AzureCliCredential

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".azure" / "evidence"
STATE = EVIDENCE / "tab-state.json"
# Private deployment inputs: names, project resource ID, and resource group.
CONFIG = ROOT / ".azure/evidence/tab-deploy-config.json"
# These are public Microsoft first-party application IDs, not tenant identities.
CLI = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
CLIENTS = ["1fec8e78-bce4-4aaf-ab1b-5451cc387264", "5e3ce6c0-2b1f-4285-8d4b-75ee78787346"]


def az(*args):
    return json.loads(subprocess.check_output(["az.cmd", *args, "-o", "json"], text=True))


def main():
    lab = json.loads((ROOT / ".azure/lab.json").read_text())
    config = json.loads(CONFIG.read_text())
    environment = az("containerapp", "env", "show", "-g", config["resource_group"],
                     "-n", config["environment_name"])
    domain = environment["properties"]["defaultDomain"]
    host = f"{config['tab_name']}.{domain}"
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    with AzureCliCredential() as credential, httpx.Client(
        base_url="https://graph.microsoft.com/v1.0",
        headers={"Authorization": "Bearer " + credential.get_token("https://graph.microsoft.com/.default").token},
        timeout=45,
    ) as graph:
        if "app_id" not in state:
            response = graph.post("/applications", json={
                "displayName": "Caldova Path6 Teams MCP Apps Tab Lab", "signInAudience": "AzureADMyOrg",
                "api": {"requestedAccessTokenVersion": 2},
            })
            response.raise_for_status()
            created = response.json()
            state.update(app_id=created["appId"], object_id=created["id"], scope_id=str(uuid.uuid4()))
            STATE.write_text(json.dumps(state, indent=2))
        resource = f"api://{host}/{state['app_id']}"
        # Azure CLI is preauthorized solely for non-GUI delegated-user backend smoke testing.
        configuration = {
            "identifierUris": [resource],
            "api": {
                "requestedAccessTokenVersion": 2,
                "oauth2PermissionScopes": [{
                    "id": state["scope_id"], "value": "access_as_user", "type": "Admin", "isEnabled": True,
                    "adminConsentDisplayName": "Access the isolated Caldova synthetic tab",
                    "adminConsentDescription": "Run bounded synthetic MCP App operations as this signed-in user.",
                    "userConsentDisplayName": "Access the Caldova lab",
                    "userConsentDescription": "Access the isolated synthetic tab.",
                }],
            },
        }
        # Graph validates preauthorization against already-persisted scopes, not
        # scopes being added in the same PATCH.
        response = graph.patch("/applications/" + state["object_id"], json=configuration)
        response.raise_for_status()
        configuration["api"]["preAuthorizedApplications"] = [
            {"appId": client, "delegatedPermissionIds": [state["scope_id"]]} for client in CLIENTS + [CLI]
        ]
        response = graph.patch("/applications/" + state["object_id"], json=configuration)
        if response.is_error:
            print("Tab registration configuration failed:", response.status_code, response.text)
        response.raise_for_status()
        if "service_principal_id" not in state:
            response = graph.post("/servicePrincipals", json={"appId": state["app_id"]})
            response.raise_for_status()
            state["service_principal_id"] = response.json()["id"]
        state.update(tenant_id=lab["tenant"], resource=resource, origin="https://" + host,
                     sandbox_origin=f"https://{config['sandbox_name']}.{domain}", diagnostic_client=CLI)
        STATE.write_text(json.dumps(state, indent=2))
        response = graph.get("/applications/" + state["object_id"],
                             params={"$select": "appId,identifierUris,api,signInAudience"})
        response.raise_for_status()
        (EVIDENCE / "tab-entra-readback.json").write_text(json.dumps(response.json(), indent=2))
    mi = az("identity", "create", "-g", config["resource_group"],
            "-n", config["identity_name"], "-l", config["location"])
    state["managed_identity"] = {key: mi[key] for key in ("id", "clientId", "principalId")}
    STATE.write_text(json.dumps(state, indent=2))
    prefix = f"/subscriptions/{lab['subscription']}/resourceGroups/{config['resource_group']}"
    registry = prefix + "/providers/Microsoft.ContainerRegistry/registries/" + config["registry_name"]
    for scope, role in [(config["project_resource_id"], "Foundry User"), (registry, "AcrPull")]:
        az("role", "assignment", "create", "--assignee-object-id", mi["principalId"],
           "--assignee-principal-type", "ServicePrincipal", "--role", role, "--scope", scope)
    print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
