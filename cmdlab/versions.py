"""Minecraft Java versions: official download lookup, data-pack format, and per-version grammar notes.

Per-version notes live in versions/<id>.json. Adding a version = adding one file.
The pack_format table below is a hint for linting before a server exists; after setup,
the real value is read from the server jar's version.json and wins.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ROOT = Path(__file__).resolve().parent.parent
VERSIONS_DIR = ROOT / "versions"

# data pack_format -> first release that uses it (hint only; verified from the jar after setup)
PACK_FORMAT_HINT = {
    15: "1.20.1", 18: "1.20.2", 26: "1.20.4", 41: "1.20.6", 48: "1.21.1", 57: "1.21.3",
    61: "1.21.4", 71: "1.21.5", 80: "1.21.6", 81: "1.21.8",
}


def notes(version: str) -> dict:
    p = VERSIONS_DIR / f"{version}.json"
    if not p.exists():
        raise SystemExit(f"version {version} has no table yet: add versions/{version}.json (see versions/1.20.1.json)")
    return json.loads(p.read_text(encoding="utf-8"))


def supported() -> list[str]:
    return sorted(p.stem for p in VERSIONS_DIR.glob("*.json"))


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def server_download(version: str) -> tuple[str, str, int]:
    """(url, sha1, size) of the official server jar for this version, from Mojang's manifest."""
    man = _get_json(MANIFEST)
    entry = next((v for v in man["versions"] if v["id"] == version), None)
    if entry is None:
        raise SystemExit(f"unknown Minecraft version: {version}")
    meta = _get_json(entry["url"])
    d = meta["downloads"]["server"]
    return d["url"], d["sha1"], d["size"]


def fetch_server(version: str, dest: Path) -> Path:
    url, sha1, _size = server_download(version)
    dest.mkdir(parents=True, exist_ok=True)
    jar = dest / f"server-{version}.jar"
    if jar.exists() and hashlib.sha1(jar.read_bytes()).hexdigest() == sha1:
        return jar
    with urllib.request.urlopen(url, timeout=300) as r:
        data = r.read()
    if hashlib.sha1(data).hexdigest() != sha1:
        raise SystemExit("downloaded server jar failed the SHA-1 check")
    jar.write_bytes(data)
    return jar


def jar_pack_format(jar: Path) -> int | None:
    """Read the data-pack format from the server jar (version.json, possibly nested in the bundler)."""
    with zipfile.ZipFile(jar) as z:
        names = z.namelist()
        if "version.json" in names:
            v = json.loads(z.read("version.json"))
            pv = v.get("pack_version")
            return pv.get("data") if isinstance(pv, dict) else pv
        inner = [n for n in names if n.startswith("META-INF/versions/") and n.endswith(".jar")]
        for n in inner:
            import io
            with zipfile.ZipFile(io.BytesIO(z.read(n))) as zi:
                if "version.json" in zi.namelist():
                    v = json.loads(zi.read("version.json"))
                    pv = v.get("pack_version")
                    return pv.get("data") if isinstance(pv, dict) else pv
    return None
