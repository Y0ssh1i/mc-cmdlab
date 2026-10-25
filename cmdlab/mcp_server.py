"""Minimal MCP server over stdio, so Claude Code / Claude Desktop can drive the test environment as tools.

Tools: list_versions, lint, setup_server, start_server, add_players, install_pack, run_script, stop_server.
It reuses the same functions as the web UI.
"""
from __future__ import annotations

import json
import sys

from .web import api

TOOLS = [
    {"name": "list_versions", "description": "Minecraft Java versions this tool supports.", "path": "/api/versions",
     "schema": {"type": "object", "properties": {}}},
    {"name": "lint", "description": "Check a data pack folder (pack_dir) or command lines against a version.", "path": "/api/lint",
     "schema": {"type": "object", "properties": {"version": {"type": "string"}, "pack_dir": {"type": "string"},
                                                  "lines": {"type": "array", "items": {"type": "string"}}},
                "required": ["version"]}},
    {"name": "setup_server", "description": "Download the official server jar and prepare a local test server. "
                                            "accept_eula must be true only if the user accepted the Minecraft EULA.",
     "path": "/api/setup", "schema": {"type": "object", "properties": {"version": {"type": "string"},
                                                                      "accept_eula": {"type": "boolean"}},
                                       "required": ["version", "accept_eula"]}},
    {"name": "start_server", "description": "Start the local test server.", "path": "/api/start",
     "schema": {"type": "object", "properties": {"version": {"type": "string"}}}},
    {"name": "add_players", "description": "Add N offline fake players named Tester1..TesterN.", "path": "/api/players",
     "schema": {"type": "object", "properties": {"count": {"type": "integer"}}}},
    {"name": "install_pack", "description": "Copy a data pack into the test world and /reload.", "path": "/api/install_pack",
     "schema": {"type": "object", "properties": {"pack_dir": {"type": "string"}}, "required": ["pack_dir"]}},
    {"name": "run_script", "description": "Run a script {steps:[...]} (one-off commands and command block lines) and get per-step results.",
     "path": "/api/run", "schema": {"type": "object", "properties": {"script": {"type": "object"}}, "required": ["script"]}},
    {"name": "stop_server", "description": "Stop players and the server.", "path": "/api/stop",
     "schema": {"type": "object", "properties": {}}},
]


def _reply(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    msg["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        m, id_ = req.get("method"), req.get("id")
        if m == "initialize":
            _reply(id_, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                         "serverInfo": {"name": "mc-cmdlab", "version": "0.1.0"}})
        elif m == "tools/list":
            _reply(id_, {"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["schema"]}
                                   for t in TOOLS]})
        elif m == "tools/call":
            p = req.get("params", {})
            t = next((t for t in TOOLS if t["name"] == p.get("name")), None)
            if not t:
                _reply(id_, error={"code": -32601, "message": "unknown tool"})
                continue
            try:
                out = api(t["path"], p.get("arguments") or {})
                _reply(id_, {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]})
            except BaseException as e:  # noqa: BLE001 - report SystemExit too, as a tool error
                _reply(id_, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        elif id_ is not None:
            _reply(id_, {})
    return 0
