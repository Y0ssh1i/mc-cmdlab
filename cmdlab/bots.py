"""Python side of the fake players: starts bots.js, collects what each player saw, and takes screen snapshots."""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME_OK = re.compile(r"^[A-Za-z0-9_]{3,16}$")  # Minecraft player names


def parse_names(names: str | list[str] | None, count: int = 3, prefix: str = "Tester") -> list[str]:
    if isinstance(names, str):
        names = [n for n in re.split(r"[\s,、]+", names) if n]
    names = list(names or [f"{prefix}{i}" for i in range(1, count + 1)])
    bad = [n for n in names if not NAME_OK.match(n)]
    if bad:
        raise SystemExit(f"player names must be 3-16 letters, digits or _: {', '.join(bad)}")
    if len(set(names)) != len(names):
        raise SystemExit("player names must be unique")
    return names


class Bots:
    def __init__(self, port: int, version: str, names: list[str]):
        self.names = names
        self.events: list[dict] = []
        self.proc = subprocess.Popen(["node", str(HERE / "bots.js"), "127.0.0.1", str(port), version, ",".join(names)],
                                     cwd=HERE.parent, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc.stdout
        for line in self.proc.stdout:
            try:
                self.events.append(json.loads(line))
            except ValueError:
                self.events.append({"event": "log", "msg": line.rstrip()})

    def _send(self, line: str) -> None:
        if self.proc.poll() is None and self.proc.stdin:
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()

    def wait_spawned(self, timeout: float = 90) -> list[str]:
        t0 = time.time()
        while time.time() - t0 < timeout:
            spawned = {e["username"] for e in self.events if e.get("event") == "spawn"}
            if spawned >= set(self.names) or self.proc.poll() is not None:
                break
            time.sleep(0.5)
        return sorted({e["username"] for e in self.events if e.get("event") == "spawn"})

    def online(self) -> set[str]:
        on = set()
        for e in self.events:
            if e.get("event") == "spawn":
                on.add(e["username"])
            elif e.get("event") in ("kicked", "end"):
                on.discard(e.get("username"))
        return on

    def screens(self, timeout: float = 5) -> list[dict]:
        """What every player sees right now: tab list, sidebar scoreboard, boss bars, title, action bar, chat."""
        mark = len(self.events)
        self._send("state")
        t0 = time.time()
        while time.time() - t0 < timeout:
            for e in self.events[mark:]:
                if e.get("event") == "state":
                    return e["screens"]
            time.sleep(0.1)
        return []

    def clear_titles(self) -> None:
        self._send("clear")

    def seen_since(self, idx: int) -> list[dict]:
        return self.events[idx:]

    def stop(self) -> None:
        if self.proc.poll() is None:
            try:
                self._send("quit")
                self.proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                self.proc.terminate()
