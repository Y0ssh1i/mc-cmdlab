"""Local web UI (open http://127.0.0.1:8765 in Chrome). Binds to 127.0.0.1 only.

Everything the page does is a plain JSON API, so an AI driving Chrome (or any HTTP client) can use it too.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import ai, explain, lint, project, runner, versions
from .bots import Bots, parse_names
from .server import TestServer

STATIC = Path(__file__).resolve().parent / "static"
WORK_LAST = Path.home() / ".mc-cmdlab" / "last_run.json"
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
RUNS = Path.home() / ".mc-cmdlab" / "runs"  # saved results per example
PROJECTS = Path.home() / ".mc-cmdlab" / "projects"  # projects saved from the editor page
STATE: dict = {"server": None, "bots": None, "last": None, "lock": threading.Lock()}


def _server(version: str | None = None) -> TestServer:
    s = STATE["server"]
    if s is None or (version and s.version != version):
        s = TestServer(version or "1.20.1")
        STATE["server"] = s
    return s


def api(path: str, body: dict) -> dict:
    # --- projects: several command sets (modules) and scenarios that combine them -------------------
    if path == "/api/projects":
        out = []
        for folder, where in ((EXAMPLES / "projects", "example"), (PROJECTS, "saved")):
            for f in sorted(folder.glob("*.json")) if folder.exists() else []:
                d = json.loads(f.read_text(encoding="utf-8"))
                out.append({"name": f.stem, "where": where, "title": d.get("title") or f.stem, "version": d.get("version"),
                            "modules": len(d.get("modules", [])), "scenarios": len(d.get("scenarios", []))})
        return out
    if path == "/api/project/load":
        name = Path(str(body.get("name", ""))).name
        for folder in (PROJECTS, EXAMPLES / "projects"):
            f = folder / f"{name}.json"
            if f.exists():
                return json.loads(f.read_text(encoding="utf-8"))
        raise SystemExit(f"no project named {name}")
    if path == "/api/project/save":
        name = Path(str(body.get("name", "") or "untitled")).name
        PROJECTS.mkdir(parents=True, exist_ok=True)
        (PROJECTS / f"{name}.json").write_text(json.dumps(body["project"], ensure_ascii=False, indent=1), encoding="utf-8")
        return {"ok": True, "saved": str(PROJECTS / f"{name}.json")}
    if path == "/api/project/check":
        p = body["project"]
        v = body.get("version") or p.get("version", "1.20.1")
        return {"problems": project.check(p), "lint": [asdict(f) for f in project.lint_project(p, v)]}
    if path == "/api/project/expand":
        return {"steps": project.scenario_steps(body["project"], body.get("scenario"), body.get("module"))}
    if path == "/api/project/export":
        p = body["project"]
        v = body.get("version") or p.get("version", "1.20.1")
        out = Path(body.get("out") or (Path.home() / ".mc-cmdlab" / "exports" / (p.get("namespace", "game") + "_" + v)))
        project.write_pack(p, out, v)
        return {"ok": True, "out": str(out)}
    if path == "/api/console":
        # type a command (or a player action) and run it right now on the test server, like the in-game chat
        s = _server()
        step = body.get("step") or {"run": body.get("command", "")}
        if body.get("as") and "run" in step:
            step["as"] = body["as"]
        res = runner.run_steps(s, STATE["bots"], [step], s.version)
        return {"result": asdict(res[0]) if res else None}
    if path == "/api/project/import_pack":
        p = project.from_datapack(Path(body["pack_dir"]), body.get("version"))
        if body.get("name"):
            PROJECTS.mkdir(parents=True, exist_ok=True)
            (PROJECTS / f"{Path(str(body['name'])).name}.json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
        return p
    if path == "/api/project/run":
        s = _server()
        p = body["project"]
        probs = project.check(p)
        if probs:
            raise SystemExit("; ".join(probs))
        dest = s.install_pack_from(lambda d: project.write_pack(p, d, s.version), "cmdlab_project")
        mark = len(s.log)
        with s.rcon() as r:
            r.command("reload")
        time.sleep(1.5)
        load_errors = explain.function_errors(s.log[mark:])
        steps = project.scenario_steps(p, body.get("scenario"), body.get("module"))
        res = runner.run_steps(s, STATE["bots"], steps, s.version, project.parse_only(body.get("only")))
        STATE["last"] = {"script": {"steps": steps}, "results": [asdict(x) for x in res]}
        WORK_LAST.write_text(json.dumps(STATE["last"]["results"], ensure_ascii=False), encoding="utf-8")
        return {"results": STATE["last"]["results"], "load_errors": load_errors, "steps": steps, "pack": str(dest)}
    if path == "/api/examples":
        out = []
        for f in sorted(EXAMPLES.glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({"name": f.stem, "title": d.get("title") or f.stem, "version": d.get("version"),
                        "steps": len(d.get("steps", [])), "has_result": (RUNS / f"{f.stem}.json").exists()})
        return out
    if path == "/api/example":
        name = Path(str(body.get("name", ""))).name
        return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))
    if path == "/api/result":
        name = Path(str(body.get("name", ""))).name
        f = RUNS / f"{name}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    if path == "/api/last":
        if STATE["last"]:
            return STATE["last"]["results"]
        f = WORK_LAST
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    if path == "/api/versions":
        return {"supported": versions.supported()}
    if path == "/api/status":
        s, b = STATE["server"], STATE["bots"]
        return {"version": s.version if s else None, "running": bool(s and s.ready),
                "screens": (b.screens(2) if b and body.get("screens") else None),
                "players": (b.wait_spawned(0) if b else []), "log": (s.log[-40:] if s else [])}
    if path == "/api/setup":
        s = _server(body["version"])
        jar = s.setup(bool(body.get("accept_eula")))
        return {"ok": True, "jar": jar.name, "pack_format": versions.jar_pack_format(jar)}
    if path == "/api/start":
        s = _server(body.get("version"))
        s.start()
        return {"ok": True}
    if path == "/api/stop":
        if STATE["bots"]:
            STATE["bots"].stop()
            STATE["bots"] = None
        if STATE["server"]:
            STATE["server"].stop()
        return {"ok": True}
    if path == "/api/players":
        s = _server()
        if STATE["bots"]:
            STATE["bots"].stop()
        names = parse_names(body.get("names"), int(body.get("count", 3)))
        b = Bots(s.port, versions.notes(s.version)["mineflayer_version"], names)
        STATE["bots"] = b
        spawned = b.wait_spawned()
        if body.get("op"):  # let test players run admin commands themselves (local test server only)
            with s.rcon() as r:
                for n in spawned:
                    r.command(f"op {n}")
        return {"ok": True, "spawned": spawned, "op": bool(body.get("op"))}
    if path == "/api/lint":
        findings = lint.lint_pack(Path(body["pack_dir"]), body["version"]) if body.get("pack_dir") else \
            lint.lint_lines(body.get("lines", []), body["version"])
        return {"findings": [asdict(f) for f in findings]}
    if path == "/api/install_pack":
        s = _server()
        dest = s.install_pack(Path(body["pack_dir"]))
        out, errs = "", []
        if s.ready:
            mark = len(s.log)
            with s.rcon() as r:
                out = r.command("reload") + "\n" + r.command("datapack list")
            time.sleep(1.5)
            errs = explain.function_errors(s.log[mark:])  # which function / line failed to load, and why
        return {"ok": True, "installed": str(dest), "server": out, "load_errors": errs}
    if path == "/api/run":
        s = _server()
        script = body["script"] if isinstance(body["script"], dict) else json.loads(body["script"])
        res = runner.run_steps(s, STATE["bots"], script["steps"], s.version)
        STATE["last"] = {"script": script, "results": [asdict(x) for x in res]}
        WORK_LAST.write_text(json.dumps(STATE["last"]["results"], ensure_ascii=False), encoding="utf-8")
        if body.get("name"):  # keep the result of each example so it can be opened again from the page
            RUNS.mkdir(parents=True, exist_ok=True)
            (RUNS / f"{Path(str(body['name'])).name}.json").write_text(json.dumps(STATE["last"]["results"], ensure_ascii=False), encoding="utf-8")
        return {"results": STATE["last"]["results"], "table": runner.to_table(res)}
    if path == "/api/ai/providers":
        return {"providers": {k: {"model": v[0], "env": v[1], "base_url": v[2] or ""} for k, v in ai.PROVIDERS.items()},
                "default": ai.DEFAULT_PROVIDER}
    if path == "/api/ai/generate":
        s = _server(body.get("version"))
        steps = ai.generate(body["request"], s.version, _ai_players(body), **_ai_opts(body))
        return {"script": {"version": s.version, "player_names": _ai_players(body), "steps": steps}}
    if path == "/api/ai/fix":
        s = _server()
        last = STATE["last"] or {}
        steps = ai.fix(body["request"], s.version, _ai_players(body),
                       last.get("script", {}).get("steps", []), last.get("results", []), **_ai_opts(body))
        return {"script": {"version": s.version, "steps": steps}}
    raise KeyError(path)


def _ai_opts(body: dict) -> dict:
    # the key is used for this one request only; it is never written to disk or logged
    return {"provider": body.get("provider") or ai.DEFAULT_PROVIDER, "model": body.get("model") or "",
            "key": body.get("key") or "", "base_url": body.get("base_url") or ""}


def _ai_players(body: dict):
    names = parse_names(body.get("names") or None, int(body.get("players", 3)))
    return names or int(body.get("players", 3))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self.path = self.path.split("?", 1)[0]
        if self.path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path in ("/editor", "/editor.html") and (STATIC / "editor.html").exists():
            return self._send(200, (STATIC / "editor.html").read_bytes(), "text/html; charset=utf-8")
        if self.path in ("/guide", "/guide.html") and (STATIC / "guide.html").exists():
            return self._send(200, (STATIC / "guide.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/snippets.json" and (STATIC / "snippets.json").exists():
            return self._send(200, (STATIC / "snippets.json").read_bytes(), "application/json; charset=utf-8")
        if self.path.startswith("/api/"):
            return self._api({})
        self._send(404, b"not found", "text/plain")

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        self._api(body)

    def _api(self, body: dict) -> None:
        try:
            with STATE["lock"]:
                out = api(self.path, body)
            self._send(200, json.dumps(out, ensure_ascii=False).encode("utf-8"), "application/json")
        except SystemExit as e:
            self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"), "application/json")
        except Exception as e:  # noqa: BLE001 - show the error in the page instead of dropping the request
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]},
                                       ensure_ascii=False).encode("utf-8"), "application/json")

    def log_message(self, *a):  # quiet
        pass


def serve(port: int = 8765) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"mc-cmdlab UI: http://127.0.0.1:{port}")
    try:
        httpd.serve_forever()
    finally:
        api("/api/stop", {})
