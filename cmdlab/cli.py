"""mc-cmdlab command line. `python -m cmdlab ui` opens the web UI; the other commands do the same from a terminal."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import ai, lint, runner, versions


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cmdlab", description="Test Minecraft Java commands locally with fake players.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("ui", help="open the web UI (http://127.0.0.1:8765)")
    u.add_argument("--port", type=int, default=8765)
    sub.add_parser("versions", help="list versions with a table in versions/")
    s = sub.add_parser("setup", help="download the official server jar and prepare a local test server")
    s.add_argument("--version", default="1.20.1")
    s.add_argument("--accept-eula", action="store_true", help="you accept https://aka.ms/MinecraftEULA")
    li = sub.add_parser("lint", help="check a data pack or a script against a version")
    li.add_argument("target", help="data pack folder or script .json")
    li.add_argument("--version", default="1.20.1")
    li.add_argument("--json", action="store_true")
    r = sub.add_parser("run", help="start the server, add players, run a script, print the result table")
    r.add_argument("script")
    r.add_argument("--version")
    r.add_argument("--players", type=int)
    r.add_argument("--pack", action="append", default=[])
    r.add_argument("--json", action="store_true")
    g = sub.add_parser("ai", help="ask an AI (Claude, OpenAI, Gemini, OpenRouter, Ollama, ...) to write a script")
    g.add_argument("request")
    g.add_argument("--version", default="1.20.1")
    g.add_argument("--players", type=int, default=3)
    g.add_argument("--out", default="ai_script.json")
    g.add_argument("--provider", default=ai.DEFAULT_PROVIDER, choices=list(ai.PROVIDERS))
    g.add_argument("--model", default=ai.DEFAULT_MODEL, help="model name (default depends on the provider)")
    g.add_argument("--base-url", default="", help="for openai_compatible / a custom endpoint")
    sub.add_parser("mcp", help="run as an MCP server over stdio (for Claude Code / Claude Desktop)")
    a = ap.parse_args(argv)
    for s_ in (sys.stdout, sys.stderr):
        try:
            s_.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    if a.cmd == "ui":
        from .web import serve
        serve(a.port)
        return 0
    if a.cmd == "versions":
        print("\n".join(versions.supported()))
        return 0
    if a.cmd == "setup":
        from .server import TestServer
        jar = TestServer(a.version).setup(a.accept_eula)
        print(f"ready: {jar} (pack_format {versions.jar_pack_format(jar)})")
        return 0
    if a.cmd == "lint":
        t = Path(a.target)
        found = lint.lint_pack(t, a.version) if t.is_dir() else \
            lint.lint_lines(runner.script_lines(runner.load_script(t)["steps"]), a.version, str(t))
        print(lint.report(found, a.json))
        return 1 if any(f.level == "error" for f in found) else 0
    if a.cmd == "run":
        from .bots import Bots, parse_names
        from .server import TestServer
        script = runner.load_script(Path(a.script))
        version = a.version or script.get("version", "1.20.1")
        players = a.players or int(script.get("players", 3))
        srv = TestServer(version)
        for p in a.pack + script.get("datapacks", []):
            srv.install_pack(Path(p))
        srv.start()
        names = parse_names(script.get("player_names"), players)
        bots = Bots(srv.port, versions.notes(version)["mineflayer_version"], names) if names else None
        try:
            if bots:
                print("players:", ", ".join(bots.wait_spawned()), file=sys.stderr)
            res = runner.run_steps(srv, bots, script["steps"], version)
            last = Path.home() / ".mc-cmdlab" / "last_run.json"
            last.write_text(runner.to_json(res), encoding="utf-8")  # the web UI can show it: /?result=1
            runs = Path.home() / ".mc-cmdlab" / "runs"
            runs.mkdir(parents=True, exist_ok=True)
            (runs / f"{Path(a.script).stem}.json").write_text(runner.to_json(res), encoding="utf-8")  # /?result=<name>
            print(runner.to_json(res) if a.json else runner.to_table(res))
            return 0 if all(x.ok for x in res) else 1
        finally:
            if bots:
                bots.stop()
            srv.stop()
    if a.cmd == "ai":
        steps = ai.generate(a.request, a.version, a.players, provider=a.provider, model=a.model, base_url=a.base_url)
        Path(a.out).write_text(json.dumps({"version": a.version, "players": a.players, "steps": steps},
                                          ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {a.out} ({len(steps)} steps)")
        return 0
    if a.cmd == "mcp":
        from .mcp_server import main as mcp_main
        return mcp_main()
    return 2
