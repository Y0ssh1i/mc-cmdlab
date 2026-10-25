"""Minimal Source RCON client (the protocol Minecraft servers speak on enable-rcon=true)."""
from __future__ import annotations

import socket
import struct

LOGIN, COMMAND = 3, 2


class RconError(RuntimeError):
    pass


def pack(req_id: int, kind: int, body: str) -> bytes:
    payload = struct.pack("<ii", req_id, kind) + body.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


def unpack(data: bytes) -> tuple[int, int, str]:
    req_id, kind = struct.unpack("<ii", data[:8])
    return req_id, kind, data[8:-2].decode("utf-8", errors="replace")


class Rcon:
    def __init__(self, host: str, port: int, password: str, timeout: float = 10.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self._id = 0
        rid, _, _ = self._send(LOGIN, password)
        if rid == -1:
            raise RconError("RCON login failed (wrong password)")

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise RconError("RCON connection closed")
            buf += chunk
        return buf

    def _send(self, kind: int, body: str) -> tuple[int, int, str]:
        self._id += 1
        self.sock.sendall(pack(self._id, kind, body))
        (length,) = struct.unpack("<i", self._recv_exact(4))
        return unpack(self._recv_exact(length))

    def command(self, cmd: str) -> str:
        return self._send(COMMAND, cmd.lstrip("/"))[2]

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
