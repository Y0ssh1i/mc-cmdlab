"""Ask an AI (Claude by default) to write a command script, then fix it from the test results.

The user's own key is read from the environment (ANTHROPIC_API_KEY). Nothing is stored in this repo.
Other providers can be added behind generate(); the prompt and the JSON shape stay the same.
"""
from __future__ import annotations

import json
import os
import re

from . import versions

DEFAULT_MODEL = os.environ.get("CMDLAB_MODEL", "claude-opus-5-5")

SYSTEM = """You write Minecraft Java Edition commands for testing a game idea on a local test server.
Return ONLY a JSON object: {"steps": [{"run": "<command without leading slash>", "as": "<optional player>",
"wait": <seconds, optional>, "expect": {<optional checks>}}]}.
Checks you may use: output_contains, output_regex, seen_by + seen_contains (text a player saw in chat/title/actionbar).
A step can also be a command block line instead of "run":
{"blocks": [{"type": "impulse|chain|repeat", "cmd": "...", "conditional": false, "auto": false}, ...],
 "origin": [x, y, z], "wait": 1, "expect_success": [true, ...]} - blocks are placed east of the origin facing east,
so chain blocks follow the first block; an impulse block without auto gets powered once by a redstone block.
Use one-off "run" steps for setup and checks, and command block lines when the idea depends on them.
Rules: use only syntax valid for the given version; test players are named Tester1..TesterN; do not use stop/op/ban/whitelist.
Set up what you need (scoreboards, teams) in early steps, then check the results with scoreboard/data/execute if commands."""


def _version_brief(version: str) -> str:
    t = versions.notes(version)
    bad = "; ".join(r["why"] for r in t.get("not_available", []))
    return f"Version {version} (data pack format {t['pack_format']}, function folder '{t['function_dir']}/'). Not available: {bad or 'none listed'}."


def _ask(prompt: str, model: str) -> str:
    try:
        import anthropic
    except ImportError as e:
        raise SystemExit("pip install anthropic   (and set ANTHROPIC_API_KEY)") from e
    client = anthropic.Anthropic()
    with client.messages.stream(model=model, max_tokens=16000, system=SYSTEM,
                                messages=[{"role": "user", "content": prompt}]) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise SystemExit("the model declined this request")
    return "".join(b.text for b in msg.content if b.type == "text")


def _parse(text: str) -> list[dict]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise SystemExit("the AI did not return a JSON script")
    return json.loads(m.group(0))["steps"]


def generate(request: str, version: str, players: int, model: str = DEFAULT_MODEL) -> list[dict]:
    prompt = f"{_version_brief(version)}\nPlayers online: Tester1..Tester{players}.\nWhat to build and test:\n{request}"
    return _parse(_ask(prompt, model))


def fix(request: str, version: str, players: int, steps: list[dict], results: list[dict],
        model: str = DEFAULT_MODEL) -> list[dict]:
    failed = [r for r in results if not r["ok"]]
    prompt = (f"{_version_brief(version)}\nPlayers: Tester1..Tester{players}.\nGoal:\n{request}\n\n"
              f"Your previous script:\n{json.dumps(steps, ensure_ascii=False)}\n\n"
              f"These steps failed on the real server (command, server reply, reason):\n"
              f"{json.dumps(failed, ensure_ascii=False)[:12000]}\n\nReturn the whole corrected script.")
    return _parse(_ask(prompt, model))
