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

from . import ai, explain, lint, runner, versions
from .bots import Bots
from .server import TestServer

STATIC = Path(__file__).resolve().parent / "static"
STATE: dict = {"server": None, "bots": None, "last": None, "lock": threading.Lock()}


def _server(version: str | None = None) -> TestServer:
    s = STATE["server"]
    if s is None or (version and s.version != version):
        s = TestServer(version or "1.20.1")
        STATE["server"] = s
    return s


def api(path: str, body: dict) -> dict:
    if path == "/api/versions":
        return {"supported": versions.supported()}
    if path == "/api/status":
        s, b = STATE["server"], STATE["bots"]
        return {"version": s.version if s else None, "running": bool(s and s.ready),
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
        b = Bots(s.port, versions.notes(s.version)["mineflayer_version"], int(body.get("count", 3)))
        STATE["bots"] = b
        return {"ok": True, "spawned": b.wait_spawned()}
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
        return {"results": STATE["last"]["results"], "table": runner.to_table(res)}
    if path == "/api/ai/generate":
        s = _server(body.get("version"))
        steps = ai.generate(body["request"], s.version, int(body.get("players", 3)))
        return {"script": {"version": s.version, "players": int(body.get("players", 3)), "steps": steps}}
    if path == "/api/ai/fix":
        s = _server()
        last = STATE["last"] or {}
        steps = ai.fix(body["request"], s.version, int(body.get("players", 3)),
                       last.get("script", {}).get("steps", []), last.get("results", []))
        return {"script": {"version": s.version, "steps": steps}}
    raise KeyError(path)


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
