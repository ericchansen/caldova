"""Generate the personal-scope custom-engine package, not a declarative plugin."""
import hashlib
import json
import struct
import uuid
import zlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]


def png(size, rgba):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\0" + bytes(rgba) * size) * size))
            + chunk(b"IEND", b""))


def main():
    state = json.loads((ROOT / ".azure/proxy-state.json").read_text())
    client_id = str(uuid.UUID(state["client_id"]))
    app_id = str(uuid.UUID(state["app_id"]))
    manifest = {
        "$schema": "https://developer.microsoft.com/json-schemas/teams/v1.24/MicrosoftTeams.schema.json",
        "manifestVersion": "1.24", "version": "1.0.0", "id": app_id,
        "developer": {"name": "Caldova", "websiteUrl": "https://github.com/ericchansen/caldova",
                      "privacyUrl": "https://privacy.microsoft.com",
                      "termsOfUseUrl": "https://www.microsoft.com/legal/terms-of-use"},
        "name": {"short": "Caldova SDK Proxy Lab", "full": "Caldova Agents SDK Custom Engine Proxy Lab"},
        "description": {"short": "Authenticated SDK proxy to the existing hosted Foundry agent",
                        "full": "Personal synthetic lab: Microsoft 365 Agents SDK delegates natural-language text to the existing Foundry hosted agent. Does not claim MCP Apps rendering."},
        "icons": {"outline": "outline.png", "color": "color.png"}, "accentColor": "#17324D",
        "bots": [{"botId": client_id, "scopes": ["personal"], "isNotificationOnly": False,
                  "supportsFiles": False}],
        "copilotAgents": {"customEngineAgents": [{"id": client_id, "type": "bot"}]},
        "validDomains": [],
    }
    output = ROOT / ".azure/proxy-personal-app.zip"
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr("color.png", png(192, (23, 50, 77, 255)))
        # Simple lab outline, transparent background with a white inset square.
        size = 32
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        pixels = b"".join(b"\0" + b"".join(
            bytes((255, 255, 255, 255 if (4 <= x < 28 and 4 <= y < 28 and
                                          (x < 7 or x >= 25 or y < 7 or y >= 25)) else 0))
            for x in range(size)) for y in range(size))
        outline = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
                   + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))
        archive.writestr("outline.png", outline)
    print(json.dumps({"package": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                      "app_id": app_id, "bot_id": client_id}, indent=2))


if __name__ == "__main__":
    main()
