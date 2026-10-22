"""Deterministic, bounded fixtures; none contain customer data."""

import hashlib
import random
import re

MAX_BYTES = 1024 * 1024
DOMAINS = (
    "orchards", "tides", "planets", "railways", "minerals", "forests",
    "satellites", "bridges", "rivers", "glaciers", "volcanoes", "gardens",
    "libraries", "observatories", "harbors", "windmills", "canals", "museums",
    "aquariums", "greenhouses", "lighthouses", "reservoirs", "tramways", "meadows",
)


def validate_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", run_id):
        raise ValueError("run_id must be 1-64 letters, digits, underscores, or hyphens")
    return run_id


def payload(size_bytes: int, run_id: str) -> str:
    validate_run_id(run_id)
    if not 1024 <= size_bytes <= MAX_BYTES:
        raise ValueError(f"size_bytes must be between 1024 and {MAX_BYTES}")
    rng = random.Random(f"{run_id}:{size_bytes}")
    text = bytearray(rng.randbytes(size_bytes).hex()[:size_bytes], "ascii")
    for label, position in (("BEGIN", 0), ("MIDDLE", size_bytes // 2), ("END", size_bytes - 96)):
        value = hashlib.sha256(f"{run_id}:{size_bytes}:{label}".encode()).hexdigest()[:24]
        marker = f"\n{label}={value}\n".encode()
        text[position:position + len(marker)] = marker
    return text.decode("ascii")


def expected_markers(size_bytes: int, run_id: str) -> dict[str, str]:
    text = payload(size_bytes, run_id)
    return dict(re.findall(r"(BEGIN|MIDDLE|END)=([0-9a-f]{24})", text))
