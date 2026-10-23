"""Bounded regional Foundry provisioner: read-only preflight and what-if; --deploy applies.

Creates only a new account (plus project, model deployment, and role assignment) in the existing
resource group. The main lab state and the original account are never modified.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from caldova import cloud

RESOURCE_GROUP = "rg-caldova-demo"
MODEL, VERSION, SKU = "gpt-5-mini", "2025-08-07", "GlobalStandard"
POLICY_URL = "https://aka.ms/azd-ai-agents/harness-region"
ARM = "https://management.azure.com"
COGNITIVE_API = "2025-06-01"
TEMPLATE = Path("infra/foundry.bicep")
SECONDARY_STATE = Path(".azure/harness-region.json")
EVIDENCE = Path("evidence")
SHARED_KEYS = ("tenant", "subscription", "principal_id", "mcp_app_id", "mcp_application_object_id",
               "mcp_service_principal_id")
SHARED_OUTPUTS = ("AZURE_RESOURCE_GROUP", "AZURE_CONTAINER_REGISTRY_ENDPOINT", "AZURE_CONTAINER_REGISTRY_NAME",
                  "MCP_ENDPOINT", "MCP_AUDIENCE", "MCP_HOST_NAME")
READ_ONLY = {"Ignore", "NoChange"}
INSIDE_ALLOWED = {"Create", "Modify", "Deploy", "Ignore", "NoChange"}


def account_name(main_account: str, location: str) -> str:
    match = re.fullmatch(r"caldova-([a-z0-9]+)", main_account)
    if not match:
        raise ValueError("Main account name doesn't have the expected caldova-<suffix> shape")
    return f"caldova-harness-{location}-{match.group(1)}"


def additional_capacity(requested: int, existing: int) -> int:
    return max(requested - existing, 0)


def check_quota(row: dict, needed: int) -> dict:
    available = row["limit"] - row["currentValue"]
    if needed > available:
        raise RuntimeError(f"Quota headroom {available} is below the additional {needed} required")
    return {"current": row["currentValue"], "limit": row["limit"], "available": available}


def parse_policy(payload: object, location: str) -> list[str]:
    regions = payload.get("regions") if isinstance(payload, dict) else None
    if not isinstance(regions, list) or not regions or not all(isinstance(r, str) for r in regions):
        raise RuntimeError("Harness region policy is malformed")
    if location not in regions:
        raise RuntimeError(f"{location} isn't in the public harness region list")
    return regions


def select_model(catalog: dict) -> dict:
    for item in catalog["value"]:
        model = item["model"]
        if (item["kind"], model["format"], model["name"], model["version"]) == ("OpenAI", "OpenAI", MODEL, VERSION):
            if model.get("lifecycleStatus") != "GenerallyAvailable":
                raise RuntimeError(f"{MODEL} {VERSION} isn't GenerallyAvailable")
            for sku in model["skus"]:
                if sku["name"] == SKU:
                    return {"usageName": sku["usageName"], "lifecycleStatus": model["lifecycleStatus"]}
    raise RuntimeError(f"{MODEL} {VERSION} {SKU} isn't offered in this region for the subscription")


def check_whatif(changes: list[dict], account_id: str) -> None:
    """Reject deletes anywhere and any non-ignorable change outside the new account namespace."""
    root = account_id.lower()
    for change in changes:
        kind, rid = change["changeType"], change["resourceId"].lower()
        inside = rid == root or rid.startswith(root + "/")
        if kind == "Delete" or (inside and kind not in INSIDE_ALLOWED) or (not inside and kind not in READ_ONLY):
            raise RuntimeError(f"What-if guard rejected {kind} {change['resourceId']}")


def merge_state(main: dict, existing: dict | None, deployed: dict, location: str) -> dict:
    """Shared identity and MCP outputs from main; Foundry outputs from this deployment.

    Agent, skill, and toolbox state survives only for the same Foundry project.
    """
    outputs = {key: main["outputs"][key] for key in SHARED_OUTPUTS}
    outputs.update(FOUNDRY_ACCOUNT_NAME=deployed["accountName"], FOUNDRY_PROJECT_ENDPOINT=deployed["projectEndpoint"],
                   FOUNDRY_MODEL=MODEL)
    state = {key: main[key] for key in SHARED_KEYS}
    managed = {*SHARED_KEYS, "outputs"}
    previous = existing or {}
    if previous.get("outputs", {}).get("FOUNDRY_PROJECT_ENDPOINT") == outputs["FOUNDRY_PROJECT_ENDPOINT"]:
        state.update({k: v for k, v in previous.items() if k not in managed})
    state["outputs"] = outputs
    state["region"] = location
    return state


def write_secondary_state(main_path: Path, secondary: Path, deployed: dict, location: str) -> None:
    main = cloud.load_state(main_path)
    existing = cloud.load_state(secondary) if secondary.exists() else None
    cloud.save_state(merge_state(main, existing, deployed, location), secondary)


class Evidence:
    """Append-only JSON lines under evidence/harness-region-*; private values are redacted."""

    def __init__(self, location: str, secrets: list[str]):
        EVIDENCE.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.path = EVIDENCE / f"harness-region-{location}-{stamp}.jsonl"
        self.secrets = [s for s in secrets if s]

    def redact(self, text: str) -> str:
        for value in self.secrets:
            text = text.replace(value, "<private>")
        return text

    def add(self, step: str, **data) -> None:
        line = self.redact(json.dumps({"utc": datetime.now(UTC).isoformat(), "step": step, **data}, default=str))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def arm_get(url: str, tenant: str, *, missing_ok: bool = False, **params) -> dict | None:
    headers = {"Authorization": f"Bearer {cloud.token(ARM, tenant)}"}
    response = httpx.get(url, headers=headers, params=params, timeout=120)
    if response.status_code == 404 and missing_ok:
        return None
    if response.is_error:
        raise RuntimeError(f"GET {url.split('/providers/')[-1]}: HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


def existing_capacity(base: str, account: str, location: str, tenant: str) -> int:
    found = arm_get(f"{base}/accounts/{account}", tenant, missing_ok=True, **{"api-version": COGNITIVE_API})
    if found is None:
        return 0
    if found["location"].replace(" ", "").lower() != location or found["kind"] != "AIServices":
        raise RuntimeError(f"Existing {account} isn't an AIServices account in {location}")
    deployment = arm_get(f"{base}/accounts/{account}/deployments/{MODEL}", tenant, missing_ok=True,
                         **{"api-version": COGNITIVE_API})
    if deployment is None:
        return 0
    model = deployment["properties"]["model"]
    if deployment["sku"]["name"] != SKU or (model["name"], model["version"]) != (MODEL, VERSION):
        raise RuntimeError(f"Existing deployment {MODEL} doesn't match {MODEL} {VERSION} {SKU}")
    return deployment["sku"]["capacity"]


def deployment_arguments(command: str, name: str, subscription: str, parameters: list[str], *extra: str) -> list[str]:
    return ["deployment", "group", command, "--subscription", subscription, "-g", RESOURCE_GROUP, "-n", name,
            "--template-file", str(TEMPLATE), "--mode", "Incremental", "--parameters", *parameters, *extra, "-o", "json"]


def run(args: argparse.Namespace) -> dict:
    main_path = cloud.STATE
    main_hash = hashlib.sha256(main_path.read_bytes()).hexdigest()
    main = cloud.load_state(main_path)
    tenant, subscription = main["tenant"], main["subscription"]
    if main["outputs"]["AZURE_RESOURCE_GROUP"] != RESOURCE_GROUP:
        raise RuntimeError(f"Main state resource group isn't {RESOURCE_GROUP}")
    location, capacity = args.location, args.capacity
    account = account_name(main["outputs"]["FOUNDRY_ACCOUNT_NAME"], location)
    if account == main["outputs"]["FOUNDRY_ACCOUNT_NAME"]:
        raise RuntimeError("Target account must differ from the original account")
    name = f"caldova-harness-{location}"
    account_id = f"/subscriptions/{subscription}/resourceGroups/{RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/{account}"
    evidence = Evidence(location, [subscription, tenant, main["principal_id"]])
    evidence.add("intention", location=location, account=account, deployment=name, capacity=capacity,
                 model=MODEL, version=VERSION, sku=SKU, deploy=args.deploy, template=str(TEMPLATE),
                 operations=["read policy", "read catalog/quota/account", "what-if Incremental"]
                 + (["deployment group create"] if args.deploy else []), main_state_sha256=main_hash)

    shown = cloud.az("account", "show", "--subscription", subscription)
    if shown["id"] != subscription or shown["tenantId"] != tenant or shown["state"] != "Enabled":
        raise RuntimeError("Azure CLI subscription doesn't match the lab state tenant/subscription")
    evidence.add("scope", state=shown["state"], tenant_match=True)

    response = httpx.get(POLICY_URL, follow_redirects=True, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"Harness region policy unavailable: HTTP {response.status_code}")
    try:
        policy = response.json()
    except ValueError as error:
        raise RuntimeError("Harness region policy is malformed") from error
    regions = parse_policy(policy, location)
    evidence.add("policy", final_url=str(response.url), regions=regions)

    group = f"{ARM}/subscriptions/{subscription}/resourceGroups/{RESOURCE_GROUP}"
    arm_get(group, tenant, **{"api-version": "2021-04-01"})
    base = f"{ARM}/subscriptions/{subscription}/resourceGroups/{RESOURCE_GROUP}/providers/Microsoft.CognitiveServices"
    catalog_url = f"{ARM}/subscriptions/{subscription}/providers/Microsoft.CognitiveServices/locations/{location}"
    offered = select_model(arm_get(f"{catalog_url}/models", tenant, **{"api-version": COGNITIVE_API}))
    evidence.add("catalog", **offered)

    existing = existing_capacity(base, account, location, tenant)
    needed = additional_capacity(capacity, existing)
    usage = [row for row in cloud.az("cognitiveservices", "usage", "list", "-l", location, "--subscription",
                                      subscription) if row["name"]["value"] == offered["usageName"]]
    if len(usage) != 1:
        raise RuntimeError(f"Expected one {offered['usageName']} usage row, found {len(usage)}")
    quota = check_quota(usage[0], needed)
    rows = arm_get(f"{catalog_url}/modelCapacities", tenant, modelFormat="OpenAI", modelName=MODEL,
                   modelVersion=VERSION, **{"api-version": "2024-10-01"})["value"]
    available = [r["properties"]["availableCapacity"] for r in rows if r["properties"]["skuName"] == SKU]
    if len(available) != 1 or available[0] < needed:
        raise RuntimeError(f"modelCapacities availability {available} is below the additional {needed} required")
    evidence.add("quota", existing=existing, requested=capacity, additional=needed, model_capacity_available=available[0],
                 **quota)

    parameters = [f"location={location}", f"accountName={account}", f"principalId={main['principal_id']}",
                  f"modelName={MODEL}", f"modelVersion={VERSION}", f"modelCapacity={capacity}"]
    result = cloud.az(*deployment_arguments("what-if", name, subscription, parameters, "--no-pretty-print",
                                            "--result-format", "ResourceIdOnly", "--no-prompt", "true"))
    if result.get("status") != "Succeeded" or not isinstance(result.get("changes"), list):
        evidence.add("what-if-failure", result=result)
        raise RuntimeError("What-if did not complete successfully with a change list")
    changes = [{"changeType": c["changeType"], "resourceId": c["resourceId"]} for c in result["changes"]]
    evidence.add("what-if", status=result.get("status"), changes=changes)
    check_whatif(changes, account_id)
    summary = {"location": location, "account": account, "model": f"{MODEL} {VERSION} {SKU}", "capacity": capacity,
               "existing": existing, "additional": needed, **quota, "whatIf": [f"{c['changeType']} {c['resourceId'].split('/providers/')[-1]}" for c in changes],
               "evidence": evidence.path.name, "deployed": False}
    if args.deploy:
        deployment = cloud.az(*deployment_arguments("create", name, subscription, parameters))
        evidence.add("deployment-result", result=deployment)
        if deployment["properties"]["provisioningState"] != "Succeeded":
            raise RuntimeError("Regional ARM deployment did not succeed")
        outputs = deployment["properties"]["outputs"]
        deployed = {key: outputs[key]["value"] for key in ("accountName", "projectEndpoint", "accountId", "projectId")}
        expected_endpoint = f"https://{account}.services.ai.azure.com/api/projects/capability-lab"
        if (deployed["accountId"].lower() != account_id.lower()
                or deployed["accountName"] != account or deployed["projectEndpoint"] != expected_endpoint
                or deployed["projectId"].lower() != (account_id + "/projects/capability-lab").lower()):
            raise RuntimeError("Deployment outputs do not match the intended regional project")
        if existing_capacity(base, account, location, tenant) != capacity:
            raise RuntimeError("Regional model readback does not match the requested capacity")
        evidence.add("deployment", accountName=deployed["accountName"], projectEndpoint=deployed["projectEndpoint"])
        if hashlib.sha256(main_path.read_bytes()).hexdigest() != main_hash:
            raise RuntimeError("Main state changed during provisioning")
        write_secondary_state(main_path, SECONDARY_STATE, deployed, location)
        evidence.add("state", path=str(SECONDARY_STATE))
        summary["deployed"] = True
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location", required=True, help="Lowercase region name, for example centralus")
    parser.add_argument("--capacity", type=int, default=400)
    parser.add_argument("--deploy", action="store_true", help="Apply after the guarded what-if passes")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-z0-9]+", args.location) or args.capacity < 1:
        parser.error("--location must be lowercase letters/digits and --capacity positive")
    try:
        print(json.dumps(run(args), indent=2))
    except (RuntimeError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        detail = re.sub(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", "<guid>",
                        getattr(error, "stderr", "") or str(error))
        print(f"harness-region failed: {type(error).__name__}: {detail[:600]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
