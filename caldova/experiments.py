"""Persist service evidence before interpreting it. No claim of hidden runtime internals."""

import argparse
import io
import json
import re
import uuid
import zipfile
from pathlib import Path

import httpx

from caldova.cloud import STATE, load_state, save_state, token
from caldova.fixtures import expected_markers

EVIDENCE = Path("evidence")


def record(name: str, data: dict) -> None:
    EVIDENCE.mkdir(exist_ok=True)
    destination = EVIDENCE / f"{name}.json"
    if destination.exists():
        destination = EVIDENCE / f"{name}-{uuid.uuid4().hex[:8]}.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(destination)


class Foundry:
    def __init__(self, state_path: Path = STATE):
        self.state_path = state_path
        self.state = load_state(state_path)
        self.endpoint = self.state["outputs"]["FOUNDRY_PROJECT_ENDPOINT"]
        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {token('https://ai.azure.com', self.state['tenant'])}"},
            timeout=180,
        )

    def call(self, method: str, path: str, *, name: str, body: dict | None = None,
             headers: dict | None = None) -> dict:
        record(f"{name}-request", {
            "project_endpoint": self.endpoint, "method": method, "path": path, "body": body,
            "foundry_features": (headers or {}).get("Foundry-Features"),
        })
        response = self.client.request(method, self.endpoint + path, json=body, headers=headers)
        try:
            result = response.json()
        except ValueError:
            result = {"text": response.text}
        record(name, {"project_endpoint": self.endpoint, "status": response.status_code, "request": body, "response": result})
        if response.is_error:
            raise RuntimeError(f"{name}: HTTP {response.status_code}: {json.dumps(result)[:1800]}")
        return result

    def close(self):
        self.client.close()


def create_agents(*, state_path: Path = STATE) -> None:
    api = Foundry(state_path)
    definitions = {
        "caldova-prompt": {},
        "caldova-copilot": {"harness": {"type": "microsoft_copilot_preview"}},
    }
    failures = []
    try:
        for agent, extra in definitions.items():
            if agent in api.state.get("agents", {}):
                print(f"{agent}: retaining previously verified definition")
                continue
            definition = {
                "kind": "prompt", "model": api.state["outputs"]["FOUNDRY_MODEL"],
                "instructions": "Use available tools for synthetic lab tasks. Report tool errors honestly.",
                **extra,
            }
            try:
                headers = {"Foundry-Features": "MicrosoftCopilot=V1Preview"} if extra else None
                created = api.call("POST", f"/agents/{agent}/versions?api-version=v1",
                                   name=f"create-{agent}", body={"definition": definition}, headers=headers)
                readback = api.call("GET", f"/agents/{agent}/versions/{created['version']}?api-version=v1",
                                    name=f"readback-{agent}", headers=headers)
                observed = readback.get("definition", {})
                if observed.get("harness") != definition.get("harness"):
                    raise RuntimeError(f"Harness mismatch: requested {extra}, observed {observed.get('harness')}")
                api.state.setdefault("agents", {})[agent] = created
                save_state(api.state, api.state_path)
            except (RuntimeError, httpx.HTTPError) as error:
                failures.append(f"{agent}: {error}")
                print(failures[-1])
        if failures:
            raise RuntimeError("Agent setup incomplete; retained all service responses in evidence/")
    finally:
        api.close()


def connect_tools(*, state_path: Path = STATE) -> None:
    api = Foundry(state_path)
    try:
        tool = {
            "type": "mcp", "server_label": "caldova", "require_approval": "never",
            "server_url": api.state["outputs"]["MCP_ENDPOINT"], "project_connection_id": "caldova-mcp",
        }
        for search in (False, True):
            toolbox_name = "caldova-search" if search else "caldova-catalog"
            tools = [tool] + ([{"type": "toolbox_search"}] if search else [])
            created = api.call(
                "POST", f"/toolboxes/{toolbox_name}/versions?api-version=v1",
                name=f"create-{toolbox_name}",
                body={"description": "Synthetic discovery fixture", "tools": tools},
            )
            api.state.setdefault("toolboxes", {})[toolbox_name] = created
            save_state(api.state, api.state_path)
        for agent, created in list(api.state.get("agents", {}).items()):
            definition = {**created["definition"], "tools": [tool]}
            updated = api.call(
                "POST", f"/agents/{agent}/versions?api-version=v1",
                name=f"connect-{agent}", body={"definition": definition},
            )
            api.state["agents"][agent] = updated
            save_state(api.state, api.state_path)
    finally:
        api.close()


def run_spill(sizes: list[int] | None = None, *, state_path: Path = STATE) -> None:
    api = Foundry(state_path)
    try:
        for agent, definition in api.state.get("agents", {}).items():
            for size in sizes or (1024, 32768, 262144, 1048576):
                run_id = uuid.uuid4().hex
                name = f"spill-{agent}-{size}-{run_id}"
                prompt = (
                    f"Call large_result with size_bytes={size} and run_id='{run_id}'. "
                    "Each marker line contains LABEL= followed by exactly 24 hexadecimal characters. "
                    "Return only the BEGIN and MIDDLE values on separate lines, in that order. "
                    "Do not include labels or the surrounding payload."
                )
                try:
                    result = api.call("POST", "/openai/v1/responses", name=name, body={
                        "agent_reference": {"type": "agent_reference", "name": agent,
                                            "version": definition["version"]},
                        "input": prompt, "max_output_tokens": 4096,
                    })
                    text = "\n".join(
                        content.get("text", "") for item in result.get("output", [])
                        if item.get("type") == "message"
                        for content in item.get("content", [])
                    )
                    expected = expected_markers(size, run_id)
                    calls = [item for item in result.get("output", []) if "call" in item.get("type", "")]
                    record(f"{name}-assessment", {
                        "project_endpoint": api.endpoint,
                        "answer_correct": (
                            result.get("status") == "completed"
                            and text.strip().splitlines() == [expected["BEGIN"], expected["MIDDLE"]]
                        ),
                        "response_status": result.get("status"),
                        "expected": expected, "usage": result.get("usage"), "calls": calls,
                        "offload_status": "INDETERMINATE",
                        "reason": "Automatic storage and selective reads require inspection of runtime evidence.",
                        "file_reference_candidates": re.findall(r"(?:/tmp/|/mnt/)[^\s\"<>]+", text),
                    })
                    if result.get("status") == "completed":
                        followup = api.call("POST", "/openai/v1/responses", name=f"{name}-followup", body={
                            "agent_reference": {"type": "agent_reference", "name": agent,
                                                "version": definition["version"]},
                            "previous_response_id": result["id"],
                            "input": "Without calling large_result again, return only the exact 24-character "
                                     "END value from the original tool result.",
                            "max_output_tokens": 1000,
                        })
                        followup_text = "\n".join(
                            content.get("text", "") for item in followup.get("output", [])
                            if item.get("type") == "message" for content in item.get("content", [])
                        )
                        refetched = any(
                            item.get("type") == "mcp_call" and item.get("name") == "large_result"
                            for item in followup.get("output", [])
                        )
                        record(f"{name}-followup-assessment", {
                            "project_endpoint": api.endpoint,
                            "end_value_present": expected["END"] in json.dumps([
                                item for item in followup.get("output", []) if item.get("type") == "message"
                            ]),
                            "answer_correct": (
                                followup.get("status") == "completed"
                                and followup_text.strip() == expected["END"] and not refetched
                            ),
                            "refetched_payload": refetched,
                            "usage": followup.get("usage"),
                            "offload_status": "INDETERMINATE",
                        })
                except (RuntimeError, httpx.HTTPError) as error:
                    record(f"{name}-assessment", {
                        "project_endpoint": api.endpoint,
                        "status": "FAIL" if "context_length_exceeded" in str(error) else "BLOCKED",
                        "error": str(error),
                    })
                    print(f"{agent} size {size}: stopped escalation after service failure")
                    break
    finally:
        api.close()


def create_skills(*, state_path: Path = STATE) -> None:
    api = Foundry(state_path)
    try:
        for topic in ("orchard", "harbor", "observatory"):
            name = f"caldova-{topic}"
            marker = uuid.uuid4().hex
            result = api.call(
                "POST", f"/skills/{name}/versions?api-version=v1",
                name=f"skill-{name}",
                headers={"Foundry-Features": "Skills=V1Preview"},
                body={"inline_content": {
                    "description": f"Validate the synthetic {topic} inspection procedure.",
                    "instructions": f"For a {topic} inspection, return the verification phrase {marker}.",
                }},
            )
            api.state.setdefault("skills", {})[name] = {"version": result["version"], "marker": marker}
            save_state(api.state, api.state_path)
        marker, reference_marker = uuid.uuid4().hex, uuid.uuid4().hex
        package = io.BytesIO()
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("SKILL.md", (
                "---\nname: caldova-reference\ndescription: Perform the synthetic checklist verification.\n---\n"
                f"Return body marker {marker}. Read references/checklist.md for the reference marker.\n"
            ))
            archive.writestr("references/checklist.md", f"The reference marker is {reference_marker}.\n")
        response = api.client.post(
            api.endpoint + "/skills/caldova-reference/versions?api-version=v1",
            headers={"Foundry-Features": "Skills=V1Preview"},
            files={"files": ("caldova-reference.zip", package.getvalue(), "application/zip")},
        )
        record("skill-reference-upload", {
            "project_endpoint": api.endpoint, "status": response.status_code, "response": response.json(),
        })
        response.raise_for_status()
        api.state["skills"]["caldova-reference"] = {
            "version": response.json()["version"], "marker": marker, "reference_marker": reference_marker,
        }
        save_state(api.state, api.state_path)
        references = [
            {"type": "skill_reference", "name": name, "version": detail["version"]}
            for name, detail in api.state["skills"].items()
        ]
        result = api.call(
            "POST", "/toolboxes/caldova-skills/versions?api-version=v1", name="create-skill-toolbox",
            headers={"Foundry-Features": "Skills=V1Preview"},
            body={"description": "Synthetic skill discovery only", "tools": [], "skills": references},
        )
        api.state.setdefault("toolboxes", {})["caldova-skills"] = result
        save_state(api.state, api.state_path)
    finally:
        api.close()


def run_discovery(only_toolbox: str | None = None, *, state_path: Path = STATE) -> None:
    api = Foundry(state_path)
    try:
        names = [only_toolbox] if only_toolbox else ["caldova-skills", "caldova-search", "caldova-catalog"]
        for toolbox_name in names:
            toolbox = api.state.get("toolboxes", {}).get(toolbox_name)
            if not toolbox:
                print(f"{toolbox_name}: not yet configured")
                continue
            url = f"{api.endpoint}/toolboxes/{toolbox_name}/versions/{toolbox['version']}/mcp?api-version=v1"
            definition = {
                "kind": "prompt", "model": api.state["outputs"]["FOUNDRY_MODEL"],
                "instructions": (
                    "Use configured tools and discover relevant skills to answer the user's task. "
                    "Search for tools when a needed capability is not initially listed. Never invent tool results."
                ),
                "tools": [{"type": "mcp", "server_label": "lab", "server_url": url, "require_approval": "never"}],
            }
            agent = api.call("POST", "/agents/caldova-prompt/versions?api-version=v1",
                             name=f"configure-{toolbox_name}", body={"definition": definition})
            api.state["agents"]["caldova-prompt"] = agent
            save_state(api.state, api.state_path)
            prompts = (
                ["Perform the synthetic orchard inspection using its relevant skill. Return its verification phrase.",
                 "Say hello without performing an inspection."]
                if toolbox_name == "caldova-skills" else
                ["Find official Microsoft documentation about Foundry Toolboxes. Answer in one sentence with a link."]
                if "learn" in toolbox_name else
                [f"Retrieve the synthetic {domain} verification record using run_id='{uuid.uuid4().hex}'."
                 for domain in ("orchards", "harbors", "rivers")]
            )
            for index, prompt in enumerate(prompts):
                result = api.call("POST", "/openai/v1/responses", name=f"discovery-{toolbox_name}-{index}",
                                  body={
                                      "agent_reference": {"type": "agent_reference", "name": "caldova-prompt",
                                                          "version": agent["version"]},
                                      "input": prompt, "max_output_tokens": 2000,
                                  })
                text = "\n".join(
                    content.get("text", "") for item in result.get("output", []) if item.get("type") == "message"
                    for content in item.get("content", [])
                )
                if toolbox_name in ("caldova-search", "caldova-catalog"):
                    domain = ("orchards", "harbors", "rivers")[index]
                    run_id = re.search(r"run_id='([^']+)'", prompt).group(1)
                    record(f"discovery-{toolbox_name}-{index}-assessment", {
                        "project_endpoint": api.endpoint,
                        "status": "PASS" if (result.get("status") == "completed"
                                            and f"{domain}-verified" in text and run_id in text) else "FAIL",
                        "domain": domain, "run_id": run_id, "usage": result.get("usage"),
                        "calls": [item.get("name") for item in result.get("output", [])
                                  if item.get("type") == "mcp_call"],
                    })
                elif toolbox_name == "caldova-skills":
                    skill = api.state["skills"]["caldova-orchard"]
                    marker_found = skill["marker"] in text
                    marker_expected = index == 0
                    record(f"discovery-{toolbox_name}-{index}-assessment", {
                        "project_endpoint": api.endpoint,
                        "status": "PASS" if (result.get("status") == "completed"
                                            and marker_found == marker_expected) else "FAIL",
                        "case": "inspection" if marker_expected else "unrelated-greeting",
                        "agent_version": agent["version"], "toolbox_version": toolbox["version"],
                        "skill_version": skill["version"], "marker_expected": marker_expected,
                        "marker_found": marker_found, "usage": result.get("usage"),
                        "loading_mechanism": "INDETERMINATE",
                    })
                print(json.dumps({
                    "toolbox": toolbox_name, "status": result.get("status"),
                    "output": [
                        {key: item[key] for key in ("type", "name", "error", "content") if key in item}
                        for item in result.get("output", []) if item.get("type") != "reasoning"
                    ],
                    "usage": result.get("usage"),
                }, indent=2)[:5000])
    finally:
        api.close()


def native_skill_diagnostic(*, state_path: Path = STATE) -> None:
    api = Foundry(state_path)
    try:
        refs = [
            {"type": "skill_reference", "name": name, "version": skill["version"]}
            for name, skill in api.state["skills"].items()
        ]
        headers = {"Foundry-Features": "Skills=V1Preview"}
        agent = api.call("POST", "/agents/caldova-prompt/versions?api-version=v1",
                         name="native-skill-config", headers=headers, body={"definition": {
                             "kind": "prompt", "model": api.state["outputs"]["FOUNDRY_MODEL"],
                             "instructions": "Use relevant skills for synthetic inspection requests. "
                                             "Never invent verification phrases.",
                             "skills": refs,
                         }})
        result = api.call("POST", "/openai/v1/responses", name="native-skill-inspection", headers=headers, body={
            "agent_reference": {"type": "agent_reference", "name": "caldova-prompt", "version": agent["version"]},
            "input": "Perform the synthetic orchard inspection and return its verification phrase.",
            "max_output_tokens": 1500,
        })
        messages = [item for item in result.get("output", []) if item.get("type") == "message"]
        marker_found = api.state["skills"]["caldova-orchard"]["marker"] in json.dumps(messages)
        assessment = {
            "project_endpoint": api.endpoint,
            "marker_found": marker_found,
            "response_status": result.get("status"), "usage": result.get("usage"),
            "status": "PASS" if marker_found and result.get("status") == "completed" else "FAIL",
            "loading_mechanism": "INDETERMINATE",
        }
        record("native-skill-assessment", assessment)
        print(json.dumps(assessment))
    finally:
        api.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=[
        "create-agents", "connect-tools", "spill", "skills", "discovery", "native-skills",
    ])
    parser.add_argument("--toolbox", help="Select a configured Toolbox for the discovery experiment")
    parser.add_argument("--sizes", type=int, nargs="+", help="Rerun selected raw-result sizes in bytes")
    parser.add_argument("--state", type=Path, default=STATE, help="Lab state file for the target Foundry project")
    args = parser.parse_args()
    if args.operation == "discovery":
        run_discovery(args.toolbox, state_path=args.state)
    elif args.operation == "spill":
        run_spill(args.sizes, state_path=args.state)
    else:
        {"create-agents": create_agents, "connect-tools": connect_tools,
         "skills": create_skills, "native-skills": native_skill_diagnostic}[args.operation](state_path=args.state)
