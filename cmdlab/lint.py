"""Check a data pack or a command script against one Minecraft version before running it."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path

from . import versions


@dataclass
class Finding:
    level: str  # error | warn
    file: str
    line: int
    message: str


def lint_lines(lines: list[str], version: str, file: str = "<script>") -> list[Finding]:
    table = versions.notes(version)
    out: list[Finding] = []
    for i, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for rule in table.get("not_available", []):
            if re.search(rule["pattern"], line):
                out.append(Finding("error", file, i, f"{rule['where']}: {rule['why']}"))
    return out


def lint_pack(pack_dir: Path, version: str) -> list[Finding]:
    table = versions.notes(version)
    out: list[Finding] = []
    meta = pack_dir / "pack.mcmeta"
    if not meta.exists():
        return [Finding("error", str(meta), 0, "pack.mcmeta not found: this is not a data pack folder")]
    pf = json.loads(meta.read_text(encoding="utf-8")).get("pack", {}).get("pack_format")
    want = table["pack_format"]
    if pf != want:
        hint = versions.PACK_FORMAT_HINT.get(pf, "an unknown version")
        out.append(Finding("error", "pack.mcmeta", 0,
                           f"pack_format {pf} is for {hint}, but {version} expects {want}. "
                           f"The server will refuse or partly ignore this pack; test on {hint} instead."))
    right = table["function_dir"]
    wrong = "functions" if right == "function" else "function"
    for ns in (pack_dir / "data").glob("*"):
        if (ns / wrong).is_dir():
            out.append(Finding("error", str(ns / wrong), 0,
                               f"folder '{wrong}/' is not read by {version}; it expects '{right}/'"))
    for f in sorted((pack_dir / "data").rglob("*.mcfunction")):
        out += lint_lines(f.read_text(encoding="utf-8", errors="replace").splitlines(), version,
                          str(f.relative_to(pack_dir)))
    return out


def report(findings: list[Finding], as_json: bool = False) -> str:
    if as_json:
        return json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=1)
    if not findings:
        return "OK: no version problems found"
    return "\n".join(f"[{f.level}] {f.file}:{f.line} {f.message}" for f in findings)
