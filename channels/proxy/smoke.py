"""Real authenticated Direct Line -> SDK -> Foundry -> SDK channel smoke.

Only new proxy bot credentials are read; kept in memory, never printed/saved.
"""
import json
import subprocess
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def az(*args):
    result = subprocess.run(["az.cmd", *args, "-o", "json"], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main():
    state = json.loads((ROOT / ".azure/proxy-state.json").read_text())
    bot = state["bot_resource_id"]
    endpoint = state["endpoint"]
    if (state["experiment"] != "path4-sdk-proxy"
            or not bot.endswith("/Microsoft.BotService/botServices/caldova-sdk-proxy")):
        raise ValueError("State does not identify the isolated proxy bot")
    run = "proxy-" + uuid.uuid4().hex[:12]
    report = {"run_id": run, "route": "DirectLine -> Agents SDK 1.9.0 -> hosted Foundry -> Activity text"}
    with httpx.Client(timeout=200) as client:
        report["anonymous_status"] = client.post(endpoint, json={"type": "message", "text": "hello"}).status_code
        report["invalid_token_status"] = client.post(
            endpoint, headers={"Authorization": "Bearer invalid"}, json={"type": "message"}).status_code
        keys = az("rest", "--method", "post", "--url",
                  f"https://management.azure.com{bot}/channels/DirectLineChannel/listChannelWithKeys?api-version=2022-09-15")
        secret = keys["properties"]["properties"]["sites"][0]["key"]
        base = "https://directline.botframework.com/v3/directline/conversations"
        start = client.post(base, headers={"Authorization": f"Bearer {secret}"})
        report["conversation_status"] = start.status_code
        start.raise_for_status()
        conversation = start.json()
        headers = {"Authorization": f"Bearer {conversation['token']}"}
        url = base + "/" + conversation["conversationId"] + "/activities"
        text = (f"Use show_table once with run_id {run}. "
                "Report its actual run ID and refresh counter. Do not call any email or send tool.")
        sent = client.post(url, headers=headers, json={
            "type": "message", "from": {"id": "proxy-lab-smoke"}, "text": text,
        })
        report["send_status"] = sent.status_code
        # Direct Line can time out its ingress request while the SDK turn keeps
        # running and replies through the authenticated Connector API.
        if sent.status_code != 502:
            sent.raise_for_status()
        report["send_body"] = sent.json()
        report["sent_activity_id"] = sent.json().get("id")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            replies = [a for a in response.json().get("activities", [])
                       if a.get("type") == "message" and a.get("from", {}).get("id") != "proxy-lab-smoke"]
            if replies:
                report["replies"] = [{k: a.get(k) for k in ("id", "text", "attachments")} for a in replies]
                break
            time.sleep(3)
        report["text_pass"] = any(run in a.get("text", "") for a in report.get("replies", []))
        report["mcp_apps_render_pass"] = None
        report["mcp_apps_note"] = "No UI driven; Activity text only is implemented. Not an Apps test."
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    main()
