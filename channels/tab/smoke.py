"""Non-GUI authenticated deployment probe. Not evidence of Teams SSO or App rendering."""
import datetime
import hashlib
import json
import uuid
from pathlib import Path

import httpx
from azure.identity import AzureCliCredential

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".azure/evidence/tab-state.json"


def main():
    state = json.loads(STATE.read_text())
    evidence = {"time": datetime.datetime.now(datetime.UTC).isoformat(),
                "boundary": "Real CLI delegated user token; no Teams/browser rendering tested", "checks": []}
    run_id = "tab-smoke-" + uuid.uuid4().hex
    with AzureCliCredential() as credential, httpx.Client(timeout=210) as client:
        bearer = credential.get_token(state["resource"] + "/.default").token
        auth = {"Authorization": "Bearer " + bearer}
        wrong_audience = credential.get_token("https://management.azure.com/.default").token
        for label, base, path, method, headers, body, expected in [
            ("static host", state["origin"], "/", "GET", {}, None, 200),
            ("anonymous RPC denied", state["origin"], "/api/rpc", "POST", {}, {"method": "tools/list"}, 401),
            ("malformed token denied", state["origin"], "/api/rpc", "POST", {"Authorization": "Bearer invalid"},
             {"method": "tools/list"}, 401),
            ("real other-audience token denied", state["origin"], "/api/rpc", "POST",
             {"Authorization": "Bearer " + wrong_audience}, {"method": "tools/list"}, 401),
            ("sandbox backend denied", state["sandbox_origin"], "/api/rpc", "POST", auth, {"method": "tools/list"}, 404),
            ("host sandbox route denied", state["origin"], "/sandbox.html", "GET", {}, None, 404),
            ("unadvertised resource denied", state["origin"], "/api/rpc", "POST", auth,
             {"method": "resources/read", "uri": "file:///etc/passwd"}, 403),
            ("other tool denied", state["origin"], "/api/rpc", "POST", auth,
             {"method": "tools/call", "name": "send_email", "arguments": {}}, 403),
            ("wrong origin denied", state["origin"], "/api/rpc", "POST",
             {**auth, "Origin": state["sandbox_origin"]}, {"method": "tools/list"}, 403),
        ]:
            response = client.request(method, base + path, headers=headers, json=body)
            check = {"name": label, "status": response.status_code, "expected": expected,
                     "pass": response.status_code == expected}
            evidence["checks"].append(check)
            print(json.dumps(check))
        for method, extra in [
            ("tools/list", {}),
            ("resources/list", {}),
            ("resources/read", {"uri": "ui://caldova/table"}),
            ("tools/call", {"name": "show_table", "arguments": {"run_id": run_id}}),
            ("tools/call", {"name": "show_table", "arguments": {"run_id": run_id}}),
        ]:
            response = client.post(state["origin"] + "/api/rpc", headers=auth, json={"method": method, **extra})
            result = response.json()
            if method == "resources/read" and response.status_code == 200:
                raw = result["contents"][0]
                evidence["resource_sha256"] = hashlib.sha256(raw["text"].encode()).hexdigest()
                csp = raw["_meta"]["ui"]["csp"]
                sandbox = client.get(state["sandbox_origin"] + "/sandbox.html",
                                     params={"csp": json.dumps(csp)})
                evidence["sandbox_status"] = sandbox.status_code
                evidence["sandbox_csp"] = sandbox.headers.get("content-security-policy")
                # Preserve resource contract metadata and hash, avoid duplicating HTML.
                result = {"contents": [{key: value for key, value in raw.items() if key != "text"}]}
            check = {"name": method, "status": response.status_code, "pass": response.status_code == 200,
                     "request_id": response.headers.get("x-request-id"), "result": result}
            evidence["checks"].append(check)
            print(json.dumps(check))
        counters = [c["result"].get("structuredContent", {}).get("counter") for c in evidence["checks"]
                    if c["name"] == "tools/call"]
        evidence["backend_repeat_counter_increased"] = len(counters) == 2 and all(
            isinstance(c, int) for c in counters) and counters[1] > counters[0]
        evidence["run_id"] = run_id
    target = ROOT / ".azure/evidence/tab-smoke.json"
    if target.exists():
        previous = json.loads(target.read_text())
        stamp = re_safe(previous["time"])
        target.with_name("tab-smoke-" + stamp + ".json").write_text(json.dumps(previous, indent=2))
    target.write_text(json.dumps(evidence, indent=2))
    print("Evidence:", target)
    print("Backend repeat counter increased:", evidence["backend_repeat_counter_increased"])
    if not all(check["pass"] for check in evidence["checks"]):
        raise SystemExit(1)


def re_safe(value):
    return "".join(char if char.isalnum() else "-" for char in value)


if __name__ == "__main__":
    main()
