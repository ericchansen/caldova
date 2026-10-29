"""Generate the tab-only Teams manifest and icons; no existing packages touched."""
import binascii
import json
import struct
import uuid
import zipfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE.parents[1] / ".azure/evidence/tab-state.json"


def png(size, color):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xffffffff)
    data = b"".join(b"\0" + bytes(color) * size for _ in range(size))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(
        b"IDAT", zlib.compress(data)) + chunk(b"IEND", b"")


def main():
    state = json.loads(STATE.read_text())
    origin = state["origin"]
    package_id = str(uuid.uuid5(uuid.NAMESPACE_URL, origin + "/teams-app"))
    manifest = {
        "$schema": "https://developer.microsoft.com/en-us/json-schemas/teams/v1.21/MicrosoftTeams.schema.json",
        "manifestVersion": "1.21",
        "version": "0.1.0",
        "id": package_id,
        "developer": {
            "name": "Caldova Capability Lab",
            "websiteUrl": origin,
            "privacyUrl": origin + "/privacy",
            "termsOfUseUrl": origin + "/terms",
        },
        "name": {"short": "Caldova MCP Apps Tab", "full": "Caldova Foundry MCP Apps authenticated tab lab"},
        "description": {
            "short": "Authenticated Teams tab hosting a synthetic Foundry-backed MCP App.",
            "full": "Isolated path6 lab. Teams SSO authenticates users. An owned backend invokes the hosted "
                    "Foundry SDK and model; the official MCP App bridge renders a separately sandboxed synthetic "
                    "table and routes Refresh back through Foundry. Not native Teams chat rendering.",
        },
        "icons": {"outline": "outline.png", "color": "color.png"},
        "accentColor": "#182338",
        "staticTabs": [{
            "entityId": "caldova-mcp-apps",
            "name": "Foundry MCP App",
            "contentUrl": origin + "/",
            "websiteUrl": origin + "/",
            "scopes": ["personal"],
        }],
        "permissions": ["identity"],
        "validDomains": [origin.removeprefix("https://"), state["sandbox_origin"].removeprefix("https://")],
        "webApplicationInfo": {"id": state["app_id"], "resource": state["resource"]},
    }
    folder = STATE.parent / "tab-package"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (folder / "color.png").write_bytes(png(192, (24, 35, 56, 255)))
    # Minimal white lab mark on transparent background, valid 32px outline format.
    raw = bytearray()
    for y in range(32):
        raw.append(0)
        for x in range(32):
            visible = (6 <= x < 10 and 6 <= y < 26) or (6 <= x < 26 and y in range(22, 26))
            raw.extend((255, 255, 255, 255 if visible else 0))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xffffffff)
    outline = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 6, 0, 0, 0))
    outline += chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b"")
    (folder / "outline.png").write_bytes(outline)
    archive = HERE.parents[1] / ".azure/tab-personal-app.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("manifest.json", "color.png", "outline.png"):
            z.write(folder / name, name)
    state.update(package_id=package_id, package_path=str(archive),
                 teams_deep_link=f"https://teams.microsoft.com/l/entity/{package_id}/caldova-mcp-apps")
    STATE.write_text(json.dumps(state, indent=2))
    print(json.dumps({key: state[key] for key in ("package_id", "package_path", "teams_deep_link", "resource")}, indent=2))


if __name__ == "__main__":
    main()
