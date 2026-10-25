"""Ask an AI to write a command script, then fix it from the test results.

Providers: Claude (Anthropic SDK), OpenAI, Google Gemini, OpenRouter, a local Ollama, or any
OpenAI-compatible endpoint. Keys come from the environment (ANTHROPIC_API_KEY, OPENAI_API_KEY,
GEMINI_API_KEY, OPENROUTER_API_KEY) or are passed in for one request. Nothing is stored in this repo.
The prompt and the JSON shape are the same for every provider.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from . import versions

# provider -> (default model, env var for the key, OpenAI-compatible base URL or None)
PROVIDERS = {
    "anthropic": ("claude-opus-5-5", "ANTHROPIC_API_KEY", None),
    "openai": ("gpt-5", "OPENAI_API_KEY", "https://api.openai.com/v1"),
    "gemini": ("gemini-2.5-pro", "GEMINI_API_KEY", None),
    "openrouter": ("anthropic/claude-opus-4.1", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
    "ollama": ("qwen2.5-coder", "", "http://127.0.0.1:11434/v1"),
    "openai_compatible": ("", "CMDLAB_API_KEY", os.environ.get("CMDLAB_BASE_URL", "")),
}
DEFAULT_PROVIDER = os.environ.get("CMDLAB_PROVIDER", "anthropic")
DEFAULT_MODEL = os.environ.get("CMDLAB_MODEL", "")

SYSTEM = """You write Minecraft Java Edition commands for testing a game idea on a local test server.
Return ONLY a JSON object: {"steps": [ ... ]}. Each step is one of:
1. One command: {"run": "<command without leading slash>", "as": "<optional player name>", "wait": <seconds, optional>,
   "expect": {<optional checks>}}
2. A command block line: {"blocks": [{"type": "impulse|chain|repeat", "cmd": "...", "conditional": false, "auto": false}, ...],
   "origin": [x, y, z], "wait": 1, "expect_success": [true, ...]} - blocks are placed east of the origin facing east,
   so chain blocks follow the first block; an impulse block without auto gets powered once by a redstone block.
3. A function (many lines, run together like a data pack function): {"function": ["line 1", "line 2", ...],
   "as": "<optional player>", "with": {<macro arguments, only on versions with macros>}, "expect": {...}}
4. A pause so scheduled functions, repeat blocks and timers can run: {"wait": <seconds>} with no command.
Checks you may use: output_contains, output_regex, seen_by + seen_contains (text a player saw in chat/title/actionbar).
Complex commands are fine: long execute chains (as/at/positioned/if/unless/store), JSON text components, NBT, selectors
with arguments. Keep JSON strings valid (escape quotes inside commands).
Rules: use only syntax valid for the given version; use the player names given; do not use stop/op/ban/whitelist.
Set up what you need (scoreboards, teams) in early steps, then check the results with scoreboard/data/execute if commands."""


def _version_brief(version: str) -> str:
    t = versions.notes(version)
    bad = "; ".join(r["why"] for r in t.get("not_available", []))
    return f"Version {version} (data pack format {t['pack_format']}, function folder '{t['function_dir']}/'). Not available: {bad or 'none listed'}."


def _post(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{url} answered {e.code}: {e.read().decode(errors='replace')[:400]}") from e


def _ask(prompt: str, provider: str, model: str, key: str = "", base_url: str = "") -> str:
    if provider not in PROVIDERS:
        raise SystemExit(f"unknown provider {provider}; choose from {', '.join(PROVIDERS)}")
    default_model, env, base = PROVIDERS[provider]
    model = model or default_model
    key = key or (os.environ.get(env, "") if env else "")
    if provider == "gemini":
        key = key or os.environ.get("GOOGLE_API_KEY", "")
    if env and not key and provider != "ollama":
        raise SystemExit(f"set {env} (or paste a key in the UI) to use {provider}")
    if provider == "anthropic":
        try:
            import anthropic
        except ImportError as e:
            raise SystemExit("pip install anthropic   (and set ANTHROPIC_API_KEY)") from e
        client = anthropic.Anthropic(api_key=key)
        with client.messages.stream(model=model, max_tokens=16000, system=SYSTEM,
                                    messages=[{"role": "user", "content": prompt}]) as stream:
            msg = stream.get_final_message()
        if msg.stop_reason == "refusal":
            raise SystemExit("the model declined this request")
        return "".join(b.text for b in msg.content if b.type == "text")
    if provider == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        out = _post(url, {"systemInstruction": {"parts": [{"text": SYSTEM}]},
                          "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                          "generationConfig": {"responseMimeType": "application/json"}},
                    {"x-goog-api-key": key})
        return "".join(p.get("text", "") for c in out.get("candidates", []) for p in c["content"].get("parts", []))
    # OpenAI and everything that speaks its chat completions API
    base = (base_url or base or "").rstrip("/")
    if not base:
        raise SystemExit("set CMDLAB_BASE_URL (or the base URL in the UI) for an OpenAI-compatible endpoint")
    if not model:
        raise SystemExit("choose a model name for this endpoint")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    out = _post(base + "/chat/completions", {"model": model, "messages": [
        {"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}, headers)
    return out["choices"][0]["message"]["content"] or ""


def _parse(text: str) -> list[dict]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise SystemExit("the AI did not return a JSON script")
    return json.loads(m.group(0))["steps"]


def _players(players) -> str:
    names = players if isinstance(players, (list, tuple)) else [f"Tester{i}" for i in range(1, int(players) + 1)]
    return ", ".join(names)


def generate(request: str, version: str, players, provider: str = DEFAULT_PROVIDER, model: str = DEFAULT_MODEL,
             key: str = "", base_url: str = "") -> list[dict]:
    prompt = f"{_version_brief(version)}\nPlayers online: {_players(players)}.\nWhat to build and test:\n{request}"
    return _parse(_ask(prompt, provider, model, key, base_url))


def fix(request: str, version: str, players, steps: list[dict], results: list[dict],
        provider: str = DEFAULT_PROVIDER, model: str = DEFAULT_MODEL, key: str = "", base_url: str = "") -> list[dict]:
    failed = [{k: r.get(k) for k in ("i", "command", "output", "why", "where_en")} for r in results if not r["ok"]]
    prompt = (f"{_version_brief(version)}\nPlayers online: {_players(players)}.\nGoal:\n{request}\n\n"
              f"Your previous script:\n{json.dumps(steps, ensure_ascii=False)}\n\n"
              f"These steps failed on the real server (step, command, server reply, reason, error position):\n"
              f"{json.dumps(failed, ensure_ascii=False)[:12000]}\n\nReturn the whole corrected script.")
    return _parse(_ask(prompt, provider, model, key, base_url))
