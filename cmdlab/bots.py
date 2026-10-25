"""Python side of the fake players: starts bots.js and collects what each player saw."""
from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


class Bots:
    def __init__(self, port: int, version: str, count: int, prefix: str = "Tester"):
        self.names = [f"{prefix}{i}" for i in range(1, count + 1)]
        self.events: list[dict] = []
        self.proc = subprocess.Popen(["node", str(HERE / "bots.js"), "127.0.0.1", str(port), version, str(count), prefix],
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

    def wait_spawned(self, timeout: float = 90) -> list[str]:
        t0 = time.time()
        while time.time() - t0 < timeout:
            spawned = {e["username"] for e in self.events if e.get("event") == "spawn"}
            if spawned >= set(self.names):
                return sorted(spawned)
            if self.proc.poll() is not None:
                break
            time.sleep(0.5)
        return sorted({e["username"] for e in self.events if e.get("event") == "spawn"})

    def seen_since(self, idx: int) -> list[dict]:
        return self.events[idx:]

    def stop(self) -> None:
        if self.proc.poll() is None:
            try:
                assert self.proc.stdin
                self.proc.stdin.write("quit\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                self.proc.terminate()
