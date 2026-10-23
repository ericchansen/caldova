"""Small deployment helpers. Local state and evidence are never committed."""

import argparse
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import httpx

STATE = Path(".azure/lab.json")
ROLE_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://caldova.example/Mcp.Access/app"))
SCOPE_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://caldova.example/Mcp.Access/user"))


def az(*arguments: str) -> dict | list:
    result = subprocess.run(
        [shutil.which("az") or "az", *arguments, "-o", "json"],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else {}


def token(resource: str, tenant: str) -> str:
    return az("account", "get-access-token", "--tenant", tenant, "--resource", resource)["accessToken"]


def request(method: str, url: str, tenant: str, resource: str, **kwargs) -> dict:
    headers = {"Authorization": f"Bearer {token(resource, tenant)}", **kwargs.pop("headers", {})}
    response = httpx.request(method, url, headers=headers, timeout=120, **kwargs)
    if response.is_error:
        raise RuntimeError(f"{method} {url}: {response.status_code}: {response.text[:4000]}")
    return response.json() if response.content else {}


def load_state(path: Path = STATE) -> dict:
    return json.loads(path.read_text())


def save_state(state: dict, path: Path = STATE) -> None:
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(path)


def bootstrap_identity() -> None:
    tenant = os.environ["AZURE_TENANT_ID"]
    subscription = os.environ["AZURE_SUBSCRIPTION_ID"]
    graph = "https://graph.microsoft.com"
    base = f"{graph}/v1.0"
    me = request("GET", f"{base}/me?$select=id", tenant, graph)
    apps = request("GET", f"{base}/applications", tenant, graph,
                   params={"$filter": "displayName eq 'caldova-mcp-fixture'", "$select": "id,appId"})
    if len(apps["value"]) > 1:
        raise RuntimeError("Multiple caldova-mcp-fixture apps exist; choose one explicitly")
    if apps["value"]:
        app = apps["value"][0]
    else:
        app = request("POST", f"{base}/applications", tenant, graph, json={
            "displayName": "caldova-mcp-fixture", "signInAudience": "AzureADMyOrg",
            "appRoles": [{
                "allowedMemberTypes": ["Application"], "description": "Read synthetic lab fixtures",
                "displayName": "Read synthetic fixtures", "id": ROLE_ID, "isEnabled": True,
                "value": "Mcp.Invoke",
            }],
            "api": {
                "requestedAccessTokenVersion": 2,
                "oauth2PermissionScopes": [{
                    "id": SCOPE_ID, "value": "Mcp.Access", "type": "User", "isEnabled": True,
                    "adminConsentDisplayName": "Read synthetic lab fixtures",
                    "adminConsentDescription": "Read Caldova synthetic fixtures",
                    "userConsentDisplayName": "Read synthetic lab fixtures",
                    "userConsentDescription": "Read Caldova synthetic fixtures",
                }],
                "preAuthorizedApplications": [{
                    "appId": "04b07795-8ddb-461a-bbee-02f9e1bf7b46", "delegatedPermissionIds": [SCOPE_ID],
                }],
            },
        })
        request("PATCH", f"{base}/applications/{app['id']}", tenant, graph,
                json={"identifierUris": [f"api://{app['appId']}"]})
    service_principals = request("GET", f"{base}/servicePrincipals", tenant, graph,
                                 params={"$filter": f"appId eq '{app['appId']}'"})
    service = service_principals["value"][0] if service_principals["value"] else request(
        "POST", f"{base}/servicePrincipals", tenant, graph, json={"appId": app["appId"]},
    )
    state = load_state() if STATE.exists() else {}
    state.update(tenant=tenant, subscription=subscription, principal_id=me["id"],
                 mcp_app_id=app["appId"], mcp_application_object_id=app["id"],
                 mcp_service_principal_id=service["id"])
    save_state(state)
    print("Synthetic MCP identity ready; identifiers saved only in ignored .azure/lab.json")


def deployment_outputs() -> None:
    state = load_state()
    result = subprocess.run(
        [shutil.which("azd") or "azd", "env", "get-values", "--output", "json"],
        check=True, capture_output=True, text=True,
    )
    values = json.loads(result.stdout)
    keys = (
        "AZURE_RESOURCE_GROUP", "FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_ACCOUNT_NAME",
        "FOUNDRY_MODEL", "AZURE_CONTAINER_REGISTRY_ENDPOINT", "AZURE_CONTAINER_REGISTRY_NAME",
        "MCP_ENDPOINT", "MCP_AUDIENCE", "MCP_HOST_NAME",
    )
    state["outputs"] = {key: values[key] for key in keys}
    save_state(state)
    print(json.dumps(state["outputs"], indent=2))


def authorize_foundry(state_path: Path = STATE) -> None:
    state = load_state(state_path)
    tenant = state["tenant"]
    graph = "https://graph.microsoft.com"
    account = state["outputs"]["FOUNDRY_ACCOUNT_NAME"]
    arm_path = (
        f"https://management.azure.com/subscriptions/{state['subscription']}"
        f"/resourceGroups/rg-caldova-demo/providers/Microsoft.CognitiveServices/accounts/{account}"
    )
    for suffix in ("", "/projects/capability-lab"):
        resource = request("GET", f"{arm_path}{suffix}?api-version=2025-06-01",
                           tenant, "https://management.azure.com/")
        principal = resource["identity"]["principalId"]
        assignments_url = f"{graph}/v1.0/servicePrincipals/{principal}/appRoleAssignments"
        existing = request("GET", assignments_url, tenant, graph)["value"]
        if not any(item["resourceId"] == state["mcp_service_principal_id"]
                   and item["appRoleId"] == ROLE_ID for item in existing):
            request("POST", assignments_url, tenant, graph, json={
                "principalId": principal, "resourceId": state["mcp_service_principal_id"],
                "appRoleId": ROLE_ID,
            })
    print("Foundry identities authorized only for the synthetic MCP application")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["identity", "outputs", "authorize"])
    parser.add_argument("--state", type=Path, default=STATE, help="State file; authorize only")
    args = parser.parse_args()
    if args.operation != "authorize" and args.state != STATE:
        parser.error("--state is supported only for authorize; identity and outputs use the main state")
    if args.operation == "authorize":
        authorize_foundry(args.state)
    else:
        {"identity": bootstrap_identity, "outputs": deployment_outputs}[args.operation]()
