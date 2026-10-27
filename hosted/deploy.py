"""Deploy only the separate hosted experiment; never update the published prompt agent."""

import argparse
import json
import time
from pathlib import Path

from caldova.cloud import load_state, save_state
from caldova.experiments import Foundry

NAME = "caldova-hosted-capabilities"


def deploy(image: str, *, state_path=Path(".azure/harness-region.json"),
           output_state=Path(".azure/hosted-centralus-state.json")) -> None:
    api = Foundry(state_path)
    try:
        lab = load_state()
        registry = lab["outputs"]["AZURE_CONTAINER_REGISTRY_ENDPOINT"]
        if not image.startswith(f"{registry}/caldova-hosted@sha256:"):
            raise ValueError("Use the immutable caldova-hosted image in this lab's registry")
        endpoint = api.endpoint
        existing = api.client.get(endpoint + f"/agents/{NAME}?api-version=v1")
        previous_endpoint = None
        if output_state.exists():
            saved = json.loads(output_state.read_text())
            if saved["name"] != NAME or saved["project_endpoint"] != endpoint:
                raise RuntimeError("Deployment state identifies a different hosted agent")
            existing.raise_for_status()
            previous_endpoint = existing.json()["agent_endpoint"]
        elif existing.status_code != 404:
            raise RuntimeError(f"Refusing untracked agent name; lookup returned {existing.status_code}")
        definition = {
            "kind": "hosted",
            "container_configuration": {"image": image},
            "cpu": "1",
            "memory": "2Gi",
            "protocol_versions": [{"protocol": "responses", "version": "2.0.0"}],
            "environment_variables": {
                "PROJECT_ENDPOINT": endpoint,
                "AZURE_AI_MODEL_DEPLOYMENT_NAME": api.state["outputs"]["FOUNDRY_MODEL"],
                "TOOLBOX_ENDPOINT": (
                    endpoint + "/toolboxes/caldova-hosted-catalog/mcp?api-version=v1"
                ),
                "MCP_ENDPOINT": lab["outputs"]["MCP_ENDPOINT"],
                "MCP_AUDIENCE": f"api://{lab['mcp_app_id']}",
            },
        }
        created = api.call(
            "POST", f"/agents/{NAME}/versions?api-version=v1",
            name="hosted-create", body={"definition": definition},
        )
        state = {"name": NAME, "version": created["version"], "project_endpoint": endpoint,
                 "image": image, "created": created}
        save_state(state, output_state)
        path = f"/agents/{NAME}/versions/{created['version']}?api-version=v1"
        for _ in range(60):
            current = api.call("GET", path, name="hosted-provisioning")
            state["current"] = current
            save_state(state, output_state)
            print("Provisioning:", current.get("status"), flush=True)
            if current.get("status") == "active":
                break
            if current.get("status") == "failed":
                raise RuntimeError(json.dumps(current.get("error", current)))
            time.sleep(5)
        else:
            raise TimeoutError("Hosted version not active after the bounded provisioning window")
        selector = {"version_selection_rules": [{
            "type": "FixedRatio", "agent_version": created["version"], "traffic_percentage": 100,
        }]}
        api.call(
            "PATCH", f"/agents/{NAME}?api-version=v1", name="hosted-route",
            body={"agent_endpoint": {
                "version_selector": selector,
                "protocol_configuration": (
                    previous_endpoint["protocol_configuration"] if previous_endpoint else {"responses": {}}
                ),
                "authorization_schemes": (
                    previous_endpoint["authorization_schemes"] if previous_endpoint
                    else [{"type": "Entra", "isolation_key_source": {"kind": "Entra"}}]
                ),
            }}, headers={"Content-Type": "application/merge-patch+json"},
        )
        readback = api.call(
            "GET", f"/agents/{NAME}?api-version=v1", name="hosted-readback",
        )
        if (readback["agent_endpoint"]["version_selector"] != selector
                or not any(x["type"] == "Entra"
                           for x in readback["agent_endpoint"]["authorization_schemes"])):
            raise RuntimeError("Hosted routing or Entra authorization readback mismatch")
        if previous_endpoint and any(
            readback["agent_endpoint"][key] != previous_endpoint[key]
            for key in ("protocol_configuration", "authorization_schemes")
        ):
            raise RuntimeError("Deployment changed existing hosted channel protocols or authentication")
        state["readback"] = readback
        save_state(state, output_state)
        print(f"Hosted agent active: {NAME}, version {created['version']}")
    finally:
        api.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--state", type=Path, default=Path(".azure/harness-region.json"))
    parser.add_argument("--output-state", type=Path, default=Path(".azure/hosted-centralus-state.json"))
    args = parser.parse_args()
    deploy(args.image, state_path=args.state, output_state=args.output_state)
