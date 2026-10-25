"""Run a command script against the test server, with fake players, and judge each step.

Script (JSON):
{
  "version": "1.20.1",
  "players": 3,
  "datapacks": ["path/to/pack"],
  "steps": [
    {"run": "say hello", "as": "Tester1"},                      # runs as that player (execute as ... at @s run ...)
    {"run": "scoreboard players get Tester1 points",
     "expect": {"output_regex": "has \\\\d+"}},                    # judge the server's reply
    {"run": "function demo:start", "wait": 2,
     "expect": {"seen_by": "Tester2", "seen_contains": "Game"}}    # judge what a player saw (chat/title/actionbar)
  ]
}
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

from . import explain, lint


@dataclass
class StepResult:
    i: int
    command: str
    ok: bool
    output: str
    seen: list[str] = field(default_factory=list)
    why: str = ""
    seconds: float = 0.0
    explain_ja: str = ""
    explain_en: str = ""
    where_ja: str = ""
    where_en: str = ""


SAFE = re.compile(r"^(?!\s*/?(stop|op|deop|ban|ban-ip|pardon|whitelist|save-off|debug|jfr|perf)\b)")


def build_command(step: dict) -> str:
    cmd = step["run"].strip().lstrip("/")
    who = step.get("as")
    if who:
        cmd = f"execute as {who} at @s run {cmd}"
    return cmd


BLOCK_ID = {"impulse": "command_block", "chain": "chain_command_block", "repeat": "repeating_command_block"}


def _nbt_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def place_blocks(r, step: dict) -> list[tuple[int, int, int]]:
    """Place a command block line (impulse/chain/repeat, conditional, always-active or needs-redstone).
    Blocks go east from the origin and face east, so a chain runs left to right. Returns block positions."""
    x0, y0, z0 = step.get("origin", [0, -59, 0])
    blocks = step["blocks"]
    r.command(f"fill {x0 - 1} {y0} {z0} {x0 + len(blocks)} {y0} {z0} air")
    pos = []
    for k, b in enumerate(blocks):
        kind = BLOCK_ID[b.get("type", "chain" if k else "impulse")]
        cond = "true" if b.get("conditional") else "false"
        auto = 1 if b.get("auto", b.get("type", "chain" if k else "impulse") != "impulse") else 0
        x = x0 + k
        r.command(f'setblock {x} {y0} {z0} minecraft:{kind}[facing=east,conditional={cond}]'
                  f'{{Command:"{_nbt_str(b["cmd"])}",auto:{auto}b,TrackOutput:1b}} replace')
        pos.append((x, y0, z0))
    first = blocks[0]
    if first.get("power", first.get("type", "impulse") == "impulse" and not first.get("auto")):
        r.command(f"setblock {x0 - 1} {y0} {z0} minecraft:redstone_block")  # needs-redstone: power it once
    return pos


def read_blocks(r, pos: list[tuple[int, int, int]]) -> list[tuple[int, str]]:
    out = []
    for x, y, z in pos:
        sc = r.command(f"data get block {x} {y} {z} SuccessCount")
        lo = r.command(f"data get block {x} {y} {z} LastOutput")
        m = re.search(r"(-?\d+)\s*$", sc.strip())
        out.append((int(m.group(1)) if m else -1, lo))
    return out


def judge(step: dict, output: str, seen: list[dict]) -> tuple[bool, str]:
    exp = step.get("expect") or {}
    low = output.lower()
    if any(w in low for w in ("unknown or incomplete command", "incorrect argument", "unknown function",
                              "expected", "no entity was found", "no player was found")) and not exp.get("allow_error"):
        return False, "server rejected the command"
    if "output_contains" in exp and exp["output_contains"] not in output:
        return False, f"output does not contain '{exp['output_contains']}'"
    if "output_regex" in exp and not re.search(exp["output_regex"], output):
        return False, f"output does not match /{exp['output_regex']}/"
    if "seen_contains" in exp:
        who = exp.get("seen_by")
        texts = [str(e.get("msg") or e.get("text") or "") for e in seen if not who or e.get("username") == who]
        if not any(exp["seen_contains"] in t for t in texts):
            return False, f"{who or 'no player'} did not see '{exp['seen_contains']}'"
    return True, ""


def run_steps(server, bots, steps: list[dict], version: str) -> list[StepResult]:
    results: list[StepResult] = []
    problems = lint.lint_lines([s.get("run", "") or " ; ".join(b.get("cmd", "") for b in s.get("blocks", []))
                                for s in steps], version)
    bad_lines = {f.line: f.message for f in problems}
    with server.rcon() as r:
        for i, step in enumerate(steps, 1):
            if step.get("blocks"):
                # command block line: place, power, wait, then read each block's SuccessCount / LastOutput
                if i in bad_lines:
                    results.append(StepResult(i, "command blocks", False, "", why=f"not valid in {version}: {bad_lines[i]}"))
                    continue
                if any(not SAFE.match(b.get("cmd", "")) for b in step["blocks"]):
                    results.append(StepResult(i, "command blocks", False, "", why="blocked: a command is not allowed in tests"))
                    continue
                mark = len(bots.events) if bots else 0
                t0 = time.time()
                pos = place_blocks(r, step)
                time.sleep(float(step.get("wait", 1.0)))
                states = read_blocks(r, pos)
                want = step.get("expect_success")  # list of booleans per block; default: every unconditional block succeeds
                fails = []
                for k, ((sc, lo), b) in enumerate(zip(states, step["blocks"])):
                    should = want[k] if want else not b.get("conditional")
                    if should and sc <= 0:
                        fails.append(f"block {k + 1} ({b.get('type', 'chain' if k else 'impulse')}) did not succeed: {lo[-120:]}")
                seen = bots.seen_since(mark) if bots else []
                ok2, why2 = judge({"expect": {k: v for k, v in (step.get("expect") or {}).items()
                                              if k.startswith("seen")}}, "", seen)
                why = "; ".join(fails + ([why2] if not ok2 else []))
                if step.get("cleanup", True):
                    x0, y0, z0 = step.get("origin", [0, -59, 0])
                    r.command(f"fill {x0 - 1} {y0} {z0} {x0 + len(pos)} {y0} {z0} air")
                results.append(StepResult(i, f"{len(pos)} command blocks: " + " → ".join(b["cmd"][:30] for b in step["blocks"]),
                                          not why, " | ".join(f"#{k + 1} success={sc}" for k, (sc, _) in enumerate(states)),
                                          [str(e.get("msg") or e.get("text") or "") for e in seen][:20], why,
                                          round(time.time() - t0, 2)))
                continue
            cmd = build_command(step)
            if not SAFE.match(step.get("run", "")):
                results.append(StepResult(i, cmd, False, "", why="blocked: this command is not allowed in tests"))
                continue
            if i in bad_lines:
                results.append(StepResult(i, cmd, False, "", why=f"not valid in {version}: {bad_lines[i]}"))
                continue
            mark = len(bots.events) if bots else 0
            t0 = time.time()
            out = r.command(cmd)
            time.sleep(float(step.get("wait", 0.3)))
            seen = bots.seen_since(mark) if bots else []
            ok, why = judge(step, out, seen)
            results.append(StepResult(i, cmd, ok, out, [str(e.get("msg") or e.get("text") or "") for e in seen
                                                         if e.get("event") in ("chat", "title", "actionbar")][:20],
                                      why, round(time.time() - t0, 2)))
    for res, step in zip(results, steps):
        if step.get("blocks"):
            n = len(step["blocks"])
            parts = [explain.describe(b["cmd"], "ja") for b in step["blocks"]]
            res.explain_ja = explain._t("blocks", "ja", n) + ": " + " → ".join(parts)
            res.explain_en = explain._t("blocks", "en", n) + ": " + " -> ".join(explain.describe(b["cmd"], "en") for b in step["blocks"])
        else:
            res.explain_ja = explain.describe(step.get("run", ""), "ja")
            res.explain_en = explain.describe(step.get("run", ""), "en")
            if not res.ok:
                res.where_ja = explain.error_location(res.command, res.output, "ja")
                res.where_en = explain.error_location(res.command, res.output, "en")
    return results


def to_table(results: list[StepResult]) -> str:
    rows = ["| # | result | command | server reply / reason |", "|---|---|---|---|"]
    for r in results:
        msg = (r.why or r.output or "").replace("|", "\\|").replace("\n", " ")[:160]
        rows.append(f"| {r.i} | {'OK' if r.ok else 'FAIL'} | `{r.command[:80]}` | {msg} |")
    passed = sum(r.ok for r in results)
    rows.append(f"\n{passed}/{len(results)} steps passed")
    return "\n".join(rows)


def to_json(results: list[StepResult]) -> str:
    return json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=1)


def load_script(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
