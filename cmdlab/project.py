"""A game project: several named command sets (modules) and several scenarios that combine them.

A real minigame is not one list of commands. It has parts such as "setup", "start", "every tick",
"when a runner is caught" and "reset", and it has to be tested in more than one order
("a normal round", "everyone gets caught", "a player leaves"). A project keeps the parts apart,
lets you order and combine them, run one part or one scenario or only some steps, and export the
whole thing as a real data pack.

{
  "version": "1.20.1",
  "title": "...",
  "namespace": "game",                      # function names become game:<module id>
  "player_names": ["Alice", "Bob"],
  "modules": [
    {"id": "setup", "label": "準備", "kind": "function", "lines": ["team add hunter", "..."], "load": true},
    {"id": "loop", "label": "毎 tick", "kind": "function", "lines": ["..."], "tick": true},
    {"id": "lobby_buttons", "label": "ロビーのボタン", "kind": "blocks", "blocks": [...], "origin": [0, -58, 10]},
    {"id": "catch_bob", "label": "Bob を捕まえる", "kind": "steps", "steps": [{"player": "Alice", "do": "attack", "target": "Bob"}]}
  ],
  "scenarios": [
    {"id": "normal", "label": "普通に1試合", "steps": [{"call": "setup"}, {"call": "catch_bob"}, {"wait": 2},
                                                   {"run": "team list jail", "expect": {"output_contains": "Bob"}}]}
  ]
}
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import lint, versions

ID_OK = re.compile(r"^[a-z0-9_./-]+$")


def is_project(script: dict) -> bool:
    return isinstance(script, dict) and "modules" in script


def check(project: dict) -> list[str]:
    """Problems that stop a project from running: bad ids, unknown calls, loops between modules."""
    probs = []
    mods = {m.get("id"): m for m in project.get("modules", [])}
    for m in project.get("modules", []):
        if not ID_OK.match(str(m.get("id", ""))):
            probs.append(f"module id '{m.get('id')}' must use a-z 0-9 _ . / - (it becomes a function name)")
        if m.get("kind", "function") not in ("function", "blocks", "steps"):
            probs.append(f"module {m.get('id')}: kind must be function, blocks or steps")
    for sc in project.get("scenarios", []):
        for s in sc.get("steps", []):
            if "call" in s and s["call"] not in mods:
                probs.append(f"scenario {sc.get('id')}: calls unknown module '{s['call']}'")
    for m in project.get("modules", []):
        for s in m.get("steps", []) if m.get("kind") == "steps" else []:
            if "call" in s and s["call"] not in mods:
                probs.append(f"module {m.get('id')}: calls unknown module '{s['call']}'")
    return probs


def _label(m: dict) -> str:
    return m.get("label") or m["id"]


def expand(project: dict, steps: list[dict], depth: int = 0) -> list[dict]:
    """Turn {"call": module} into the steps that run it, so the runner sees plain steps."""
    if depth > 8:
        raise SystemExit("modules call each other too deeply (a loop?)")
    ns = project.get("namespace", "game")
    mods = {m["id"]: m for m in project.get("modules", [])}
    out: list[dict] = []
    for s in steps:
        if "call" not in s:
            out.append(dict(s))
            continue
        m = mods[s["call"]]
        kind = m.get("kind", "function")
        extra = {k: v for k, v in s.items() if k != "call"}
        if kind == "function":
            out.append({"run": f"function {ns}:{m['id']}", **extra, "_module": _label(m)})
        elif kind == "blocks":
            blk = {"blocks": m["blocks"], "origin": m.get("origin", [0, -58, 10]), "wait": m.get("wait", 1),
                   "cleanup": m.get("cleanup", False)}
            for k in ("facing", "trigger", "expect_success"):  # keep how the line is built and powered
                if k in m:
                    blk[k] = m[k]
            out.append({**blk, **extra, "_module": _label(m)})
        else:
            for x in expand(project, m.get("steps", []), depth + 1):
                x.setdefault("_module", _label(m))
                out.append(x)
    return out


def scenario_steps(project: dict, scenario: str | None = None, module: str | None = None) -> list[dict]:
    """The steps to run: one scenario (default: the first one), or just one module on its own."""
    if module:
        return expand(project, [{"call": module}])
    scs = project.get("scenarios", [])
    if not scs:
        return expand(project, [{"call": m["id"]} for m in project.get("modules", [])])
    sc = next((x for x in scs if x.get("id") == scenario), scs[0]) if scenario else scs[0]
    return expand(project, sc.get("steps", []))


def write_pack(project: dict, dest: Path, version: str) -> Path:
    """Write the function modules as a real data pack (functions + tick/load tags) for this version."""
    t = versions.notes(version)
    ns = project.get("namespace", "game")
    if dest.exists():
        shutil.rmtree(dest)
    fdir = dest / "data" / ns / t["function_dir"]
    tagdir = dest / "data" / "minecraft" / "tags" / t["function_dir"]
    fdir.mkdir(parents=True)
    tagdir.mkdir(parents=True)
    (dest / "pack.mcmeta").write_text(json.dumps({"pack": {"pack_format": t["pack_format"],
                                                           "description": project.get("title", "mc-cmdlab project")}},
                                                 ensure_ascii=False, indent=2), encoding="utf-8")
    tick, load = [], []
    for m in project.get("modules", []):
        if m.get("kind", "function") != "function":
            continue
        path = fdir / f"{m['id']}.mcfunction"
        path.parent.mkdir(parents=True, exist_ok=True)
        head = [f"# {_label(m)}"] + ([f"# {m['note']}"] if m.get("note") else [])
        path.write_text("\n".join(head + list(m.get("lines", []))) + "\n", encoding="utf-8")
        if m.get("tick"):
            tick.append(f"{ns}:{m['id']}")
        if m.get("load"):
            load.append(f"{ns}:{m['id']}")
    for name, vals in (("tick", tick), ("load", load)):
        if vals:
            (tagdir / f"{name}.json").write_text(json.dumps({"values": vals}, indent=2), encoding="utf-8")
    return dest


def lint_project(project: dict, version: str) -> list[lint.Finding]:
    out = []
    for m in project.get("modules", []):
        if m.get("kind", "function") == "function":
            out += lint.lint_lines(m.get("lines", []), version, f"module {m['id']}")
        elif m.get("kind") == "blocks":
            out += lint.lint_lines([b.get("cmd", "") for b in m.get("blocks", [])], version, f"module {m['id']}")
    return out


def parse_only(text: str | None) -> set[int] | None:
    """'3,5-7' -> {3, 5, 6, 7}. None or '' means every step."""
    if not text:
        return None
    out: set[int] = set()
    for part in str(text).replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    return out
