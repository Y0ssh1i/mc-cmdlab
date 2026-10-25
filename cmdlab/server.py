"""Run a local, offline test server for one Minecraft version (official jar, RCON on, flat world)."""
from __future__ import annotations

import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import versions
from .rcon import Rcon

WORK = Path.home() / ".mc-cmdlab"


class TestServer:
    def __init__(self, version: str, port: int = 25565, rcon_port: int = 25575, work: Path = WORK):
        self.version = version
        self.port = port
        self.rcon_port = rcon_port
        self.dir = work / "servers" / version
        self.proc: subprocess.Popen | None = None
        self.log: list[str] = []
        self.password = ""
        self.ready = False

    # --- setup -----------------------------------------------------------
    def setup(self, accept_eula: bool) -> Path:
        if not accept_eula:
            raise SystemExit("The Minecraft EULA must be accepted by you to run a server: "
                             "https://aka.ms/MinecraftEULA  (pass --accept-eula / tick the box in the UI)")
        jar = versions.fetch_server(self.version, self.dir)
        (self.dir / "eula.txt").write_text("eula=true\n", encoding="utf-8")
        self.password = secrets.token_hex(12)
        props = {
            "online-mode": "false",          # local fake players only; never expose this server
            "server-ip": "127.0.0.1",
            "server-port": str(self.port),
            "enable-rcon": "true",
            "rcon.port": str(self.rcon_port),
            "rcon.password": self.password,
            "level-type": "minecraft\\:flat",
            "spawn-protection": "0",
            "max-players": "50",
            "enable-command-block": "true",
            "function-permission-level": "4",
            "broadcast-rcon-to-ops": "false",
            "motd": "mc-cmdlab test server",
        }
        (self.dir / "server.properties").write_text("".join(f"{k}={v}\n" for k, v in props.items()), encoding="utf-8")
        return jar

    def install_pack(self, pack_dir: Path, name: str | None = None) -> Path:
        dest = self.dir / "world" / "datapacks" / (name or pack_dir.name)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(pack_dir, dest, ignore=shutil.ignore_patterns(".git"))
        return dest

    def install_pack_from(self, writer, name: str) -> Path:
        """Write a generated data pack straight into this server's world (used for projects)."""
        dest = self.dir / "world" / "datapacks" / name
        writer(dest)
        return dest

    # --- run ---------------------------------------------------------------
    def reset_world(self) -> None:
        """Start each test from a clean world, keeping the installed data packs."""
        world = self.dir / "world"
        if not world.exists():
            return
        packs = world / "datapacks"
        keep = self.dir / "_datapacks_keep"
        if keep.exists():
            shutil.rmtree(keep)
        if packs.exists():
            shutil.move(str(packs), str(keep))
        shutil.rmtree(world)
        if keep.exists():
            world.mkdir()
            shutil.move(str(keep), str(packs))

    def use_world(self, world_dir: Path) -> None:
        """Test on a copy of a real world (your map with its command blocks); the original is never touched."""
        world_dir = Path(world_dir)
        if not (world_dir / "level.dat").exists():
            raise SystemExit(f"{world_dir} is not a Minecraft world folder (no level.dat)")
        dest = self.dir / "world"
        keep = None
        if (dest / "datapacks").exists():
            keep = self.dir / "_datapacks_keep"
            if keep.exists():
                shutil.rmtree(keep)
            shutil.move(str(dest / "datapacks"), str(keep))
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(world_dir, dest, ignore=shutil.ignore_patterns("session.lock"))
        if keep:
            (dest / "datapacks").mkdir(exist_ok=True)
            for p in keep.iterdir():
                target = dest / "datapacks" / p.name
                if target.exists():
                    shutil.rmtree(target) if target.is_dir() else target.unlink()
                shutil.move(str(p), str(target))
            shutil.rmtree(keep)

    def start(self, memory: str = "2G", timeout: float = 240, fresh: bool = True, world: Path | None = None) -> None:
        jar = self.dir / f"server-{self.version}.jar"
        if not jar.exists():
            raise SystemExit(f"run setup for {self.version} first")
        if world:
            self.use_world(world)
        elif fresh:
            self.reset_world()
        if not self.password:
            for line in (self.dir / "server.properties").read_text(encoding="utf-8").splitlines():
                if line.startswith("rcon.password="):
                    self.password = line.split("=", 1)[1]
        self.proc = subprocess.Popen(["java", f"-Xmx{memory}", "-jar", jar.name, "nogui"], cwd=self.dir,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace")
        threading.Thread(target=self._pump, daemon=True).start()
        t0 = time.time()
        while not self.ready:
            if self.proc.poll() is not None:
                raise SystemExit("server exited during start:\n" + "\n".join(self.log[-30:]))
            if time.time() - t0 > timeout:
                raise SystemExit("server did not finish starting in time")
            time.sleep(0.5)

    def _pump(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.rstrip()
            self.log.append(line)
            if len(self.log) > 2000:
                del self.log[:500]
            if "Done (" in line and "For help" in line:
                self.ready = True

    def rcon(self) -> Rcon:
        return Rcon("127.0.0.1", self.rcon_port, self.password)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                with self.rcon() as r:
                    r.command("stop")
                self.proc.wait(timeout=60)
            except Exception:  # noqa: BLE001 - fall back to terminating our own child
                self.proc.terminate()
        self.ready = False
