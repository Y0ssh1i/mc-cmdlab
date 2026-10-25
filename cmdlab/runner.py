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

from . import explain, lint, versions


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
    screens: list = field(default_factory=list)  # what each player saw on screen right after this step


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


DIRS = {"east": (1, 0, 0), "west": (-1, 0, 0), "south": (0, 0, 1), "north": (0, 0, -1), "up": (0, 1, 0), "down": (0, -1, 0)}


def layout(step: dict) -> list[tuple[int, int, int, str]]:
    """Where each command block of a line goes, like a real build: a line starts at "origin" and runs in
    "facing" (default east); a block may set its own "facing" to turn the line (up, north ...), or give an
    exact "pos". The next chain block always sits in front of the previous block, as in the game."""
    x, y, z = step.get("origin", [0, -59, 0])
    facing = step.get("facing", "east")
    out = []
    for b in step["blocks"]:
        if b.get("pos"):
            x, y, z = b["pos"]
        facing = b.get("facing", facing)
        out.append((x, y, z, facing))
        dx, dy, dz = DIRS[facing]
        x, y, z = x + dx, y + dy, z + dz
    return out


def place_blocks(r, step: dict) -> list[tuple[int, int, int]]:
    """Place a command block line (impulse/chain/repeat, conditional, always-active or needs-redstone) the way
    it would be built in the world, then power it: "trigger" is "redstone_block" (default for an impulse block
    without auto), "button" (a stone button is placed on top so a test player can press it), or "none"."""
    blocks = step["blocks"]
    spots = layout(step)
    pos = []
    for k, (b, (x, y, z, facing)) in enumerate(zip(blocks, spots)):
        kind = BLOCK_ID[b.get("type", "chain" if k else "impulse")]
        cond = "true" if b.get("conditional") else "false"
        auto = 1 if b.get("auto", b.get("type", "chain" if k else "impulse") != "impulse") else 0
        r.command(f'setblock {x} {y} {z} minecraft:{kind}[facing={facing},conditional={cond}]'
                  f'{{Command:"{_nbt_str(b["cmd"])}",auto:{auto}b,TrackOutput:1b}} replace')
        pos.append((x, y, z))
    first = blocks[0]
    x0, y0, z0, f0 = spots[0]
    needs_power = first.get("type", "impulse") != "chain" and not first.get("auto")
    trigger = step.get("trigger", "redstone_block" if needs_power else "none")
    if trigger == "redstone_block":
        dx, dy, dz = DIRS[f0]
        r.command(f"setblock {x0 - dx} {y0 - dy} {z0 - dz} minecraft:redstone_block")  # behind the first block
    elif trigger == "button":
        r.command(f"setblock {x0} {y0 + 1} {z0} minecraft:stone_button[face=floor]")
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
    for key, ev in (("died", "death"), ("hurt", "hurt")):
        if key in exp:
            who = exp[key]
            if not any(e.get("event") == ev and e.get("username") == who for e in seen):
                return False, f"{who} was not {'killed' if key == 'died' else 'hurt'}"
    if "heard" in exp:  # {"heard": "experience_orb"} or {"heard": "...", "heard_by": "Alice"}: a sound reached a player
        who = exp.get("heard_by")
        if not any(e.get("event") == "sound" and exp["heard"] in str(e.get("name", "")) and (not who or e.get("username") == who) for e in seen):
            return False, f"{who or 'no player'} heard no sound matching '{exp['heard']}'"
    if "seen_contains" in exp:
        who = exp.get("seen_by")
        texts = [str(e.get("msg") or e.get("text") or "") for e in seen if not who or e.get("username") == who]
        if not any(exp["seen_contains"] in t for t in texts):
            return False, f"{who or 'no player'} did not see '{exp['seen_contains']}'"
    return True, ""


def write_functions(server, steps: list[dict], version: str) -> dict[int, str]:
    """Write every {"function": [...]} step into one small data pack, so it runs exactly like a real
    data pack function (macros, many lines, execute chains). Returns {step: problem} for lines that fail lint."""
    t = versions.notes(version)
    pack = Path(server.dir) / "world" / "datapacks" / "cmdlab_steps"
    fdir = pack / "data" / "cmdlab" / t["function_dir"]
    if pack.exists():
        import shutil
        shutil.rmtree(pack)
    bad = {}
    if not any(s.get("function") for s in steps):
        return bad
    fdir.mkdir(parents=True)
    (pack / "pack.mcmeta").write_text(json.dumps({"pack": {"pack_format": t["pack_format"],
                                                           "description": "mc-cmdlab test steps"}}), encoding="utf-8")
    for i, s in enumerate(steps, 1):
        if s.get("function"):
            lines = s["function"] if isinstance(s["function"], list) else str(s["function"]).splitlines()
            errs = [f for f in lint.lint_lines(lines, version, f"step{i}") if f.level == "error"]
            if errs:
                bad[i] = "; ".join(f"line {f.line}: {f.message}" for f in errs)
            if any(not SAFE.match(x) for x in lines):
                bad[i] = "blocked: a command is not allowed in tests"
            (fdir / f"step{i}.mcfunction").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return bad


def run_steps(server, bots, steps: list[dict], version: str, only: set[int] | None = None) -> list[StepResult]:
    """Run the steps in order. With "only" (step numbers), run just those steps and skip the rest."""
    results: list[StepResult] = []
    problems = lint.lint_lines([s.get("run", "") or " ; ".join(b.get("cmd", "") for b in s.get("blocks", []))
                                for s in steps], version)
    bad_lines = {f.line: f.message for f in problems if f.level == "error"}
    bad_funcs = write_functions(server, steps, version)
    with server.rcon() as r:
        load_errors: list[str] = []
        if any(s.get("function") for s in steps):
            mark = len(server.log)
            r.command("reload")
            time.sleep(1.5)
            load_errors = explain.function_errors(server.log[mark:])
        for i, step in enumerate(steps, 1):
            if only and i not in only:
                continue
            if step.get("function"):
                # many lines run together as a data pack function (optionally as a player, with macro arguments)
                name = f"cmdlab:step{i}"
                cmd = f"function {name}" + (" " + json.dumps(step["with"], ensure_ascii=False) if step.get("with") else "")
                if step.get("as"):
                    cmd = f"execute as {step['as']} at @s run {cmd}"
                mine = [e for e in load_errors if f"step{i}" in e]
                if i in bad_funcs or mine:
                    results.append(StepResult(i, cmd, False, "\n".join(mine), why=bad_funcs.get(i) or "the function did not load"))
                    continue
                mark = len(bots.events) if bots else 0
                t0 = time.time()
                out = r.command(cmd)
                time.sleep(float(step.get("wait", 0.5)))
                seen = bots.seen_since(mark) if bots else []
                ok, why = judge(step, out, seen)
                results.append(StepResult(i, cmd, ok, out, [str(e.get("msg") or e.get("text") or "") for e in seen
                                                             if e.get("event") in ("chat", "title", "actionbar")][:20],
                                          why, round(time.time() - t0, 2)))
                if bots:
                    results[-1].screens = bots.screens()
                continue
            if step.get("do"):
                # a test player acts like a person: chat, command (/trigger ...), move, goto, look_at, attack ...
                who = step.get("player", "")
                action = {k: v for k, v in step.items() if k not in ("player", "expect", "wait")}
                action["action"] = action.pop("do")
                label = f"{who}: {action['action']} " + " ".join(f"{k}={v}" for k, v in action.items() if k != "action")
                if not bots or who not in bots.online():
                    results.append(StepResult(i, label, False, "", why=f"player {who} is not online"))
                    continue
                if action["action"] in ("chat", "command") and not SAFE.match(str(action.get("text", "")).lstrip("/")):
                    results.append(StepResult(i, label, False, "", why="blocked: this command is not allowed in tests"))
                    continue
                mark = len(bots.events)
                t0 = time.time()
                res = bots.act(who, action)
                time.sleep(float(step.get("wait", 0.5)))
                seen = bots.seen_since(mark)
                ok, why = (False, res.get("error", "the action failed")) if not res.get("ok") else judge(step, "", seen)
                results.append(StepResult(i, label, ok, json.dumps(res.get("position") or {}, ensure_ascii=False) if res.get("ok") else "",
                                          [str(e.get("msg") or e.get("text") or (f"{e['username']} died" if e.get("event") == "death" else ""))
                                           for e in seen if e.get("event") in ("chat", "title", "actionbar", "death")][:20],
                                          why, round(time.time() - t0, 2)))
                results[-1].screens = bots.screens()
                continue
            if not step.get("run") and not step.get("blocks"):
                # just let time pass (scheduled functions, repeat blocks, timers)
                time.sleep(float(step.get("wait", 1.0)))
                results.append(StepResult(i, f"wait {step.get('wait', 1.0)}s", True, ""))
                if bots:
                    results[-1].screens = bots.screens()
                continue
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
                    if want is False:  # a watcher line (e.g. a repeat that waits for a condition): no success expected
                        continue
                    should = want[k] if want else not b.get("conditional")
                    if should and sc <= 0:
                        fails.append(f"block {k + 1} ({b.get('type', 'chain' if k else 'impulse')}) did not succeed: {lo[-120:]}")
                seen = bots.seen_since(mark) if bots else []
                ok2, why2 = judge({"expect": {k: v for k, v in (step.get("expect") or {}).items()
                                              if k.startswith("seen")}}, "", seen)
                why = "; ".join(fails + ([why2] if not ok2 else []))
                if step.get("cleanup", True):
                    for (x, y, z) in pos:
                        r.command(f"setblock {x} {y} {z} air")
                    x0, y0, z0, f0 = layout(step)[0]
                    dx, dy, dz = DIRS[f0]
                    r.command(f"setblock {x0 - dx} {y0 - dy} {z0 - dz} air")
                    r.command(f"setblock {x0} {y0 + 1} {z0} air")
                results.append(StepResult(i, f"{len(pos)} command blocks: " + " → ".join(b["cmd"][:30] for b in step["blocks"]),
                                          not why, " | ".join(f"#{k + 1} success={sc}" for k, (sc, _) in enumerate(states)),
                                          [str(e.get("msg") or e.get("text") or "") for e in seen][:20], why,
                                          round(time.time() - t0, 2)))
                if bots:
                    results[-1].screens = bots.screens()
                continue
            cmd = build_command(step)
            if not SAFE.match(step.get("run", "")):
                results.append(StepResult(i, cmd, False, "", why="blocked: this command is not allowed in tests"))
                continue
            if i in bad_lines:
                results.append(StepResult(i, cmd, False, "", why=f"not valid in {version}: {bad_lines[i]}"))
                continue
            who = step.get("as")
            if who and bots and who not in bots.online():
                results.append(StepResult(i, cmd, False, "", why=f"player {who} is not online, so nothing ran"))
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
            if bots:
                results[-1].screens = bots.screens()
    for res in results:
        step = steps[res.i - 1]
        if step.get("blocks"):
            n = len(step["blocks"])
            parts = [explain.describe(b["cmd"], "ja") for b in step["blocks"]]
            res.explain_ja = explain._t("blocks", "ja", n) + ": " + " → ".join(parts)
            res.explain_en = explain._t("blocks", "en", n) + ": " + " -> ".join(explain.describe(b["cmd"], "en") for b in step["blocks"])
        elif step.get("function"):
            lines = step["function"] if isinstance(step["function"], list) else str(step["function"]).splitlines()
            body = [x for x in lines if x.strip() and not x.strip().startswith("#")]
            who = f"{step['as']} として" if step.get("as") else ""
            res.explain_ja = f"{who}関数として {len(body)} 行を実行: " + " → ".join(explain.describe(x.lstrip("$"), "ja") for x in body[:6]) + (" …" if len(body) > 6 else "")
            res.explain_en = (f"As {step['as']}, run" if step.get("as") else "Run") + f" {len(body)} lines as a function: " +                 " -> ".join(explain.describe(x.lstrip("$"), "en") for x in body[:6]) + (" ..." if len(body) > 6 else "")
        elif step.get("do"):
            res.explain_ja = explain.describe_action(step, "ja")
            res.explain_en = explain.describe_action(step, "en")
        elif not step.get("run"):
            res.explain_ja = f"{step.get('wait', 1.0)} 秒待つ(予約した関数・リピートブロック・タイマーが動く時間)"
            res.explain_en = f"Wait {step.get('wait', 1.0)} s (lets scheduled functions, repeat blocks and timers run)"
        else:
            res.explain_ja = explain.describe(build_command(step), "ja")
            res.explain_en = explain.describe(build_command(step), "en")
            if not res.ok:
                res.where_ja = explain.error_location(res.command, res.output, "ja")
                res.where_en = explain.error_location(res.command, res.output, "en")
        if step.get("_module"):
            res.explain_ja = f"[{step['_module']}] " + res.explain_ja
            res.explain_en = f"[{step['_module']}] " + res.explain_en
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


def script_lines(steps: list[dict]) -> list[str]:
    """Every command in a script (one-off, command blocks, function lines), for linting."""
    out = []
    for s in steps:
        if s.get("function"):
            out += s["function"] if isinstance(s["function"], list) else str(s["function"]).splitlines()
        out += [b.get("cmd", "") for b in s.get("blocks", [])]
        if s.get("run"):
            out.append(s["run"])
    return out


def load_script(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
