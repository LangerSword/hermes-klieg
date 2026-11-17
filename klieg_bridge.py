"""The live bridge: talk to a Blender that is already running.

Batch is reliable because it is a process you own. A live session is the opposite: the
host is somebody else's event loop, it can be busy, it can be showing a modal dialog, and
it can die mid-call. So the protocol here is deliberately narrow and defensive:

    request : one JSON object per line, {"op": "eval", "code": "...", "expr": "...", "id": 7}
    response: one JSON object per line, {"id": 7, "ok": true, "result": "..."}

Rules that make it survivable:
  - a per-call timeout, and a distinct exception for "connected but silent" so the caller
    can tell a busy host from a dead one
  - the host executes on its own main thread; the plugin never assumes it can interrupt it
  - `eval` is the only verb that can do damage, and it is approval-gated at the tool layer
"""

from __future__ import annotations

import json
import os
import socket

DEFAULT_TIMEOUT = 15.0


class BridgeError(RuntimeError):
    pass


class BridgeTimeout(BridgeError):
    """Connected, but no reply in time. The host is busy or showing a dialog."""


class BridgeUnavailable(BridgeError):
    """No socket, or nobody listening: the host is not running the bridge."""


def default_socket(pid: int | None = None) -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(base, f"klieg-{pid}.sock" if pid else "klieg.sock")


class Bridge:
    """One call = one connection. Cheap, and immune to a half-closed stream."""

    def __init__(self, path: str | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.path = path or default_socket()
        self.timeout = timeout

    def alive(self) -> bool:
        return os.path.exists(self.path)

    def call(self, op: str, **kw) -> dict:
        if not self.alive():
            raise BridgeUnavailable(f"no socket at {self.path}")
        req = {"op": op, "id": int(kw.pop("id", 1)), **kw}
        payload = (json.dumps(req) + "\n").encode()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.connect(self.path)
        except OSError as e:
            raise BridgeUnavailable(f"connect failed: {e}") from e
        try:
            s.sendall(payload)
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        except socket.timeout as e:
            raise BridgeTimeout(
                f"{self.path} accepted the connection but did not answer in {self.timeout}s "
                "(the host is busy or modal)") from e
        except OSError as e:
            raise BridgeUnavailable(f"transport failed: {e}") from e
        finally:
            s.close()
        if not buf.strip():
            raise BridgeUnavailable("host closed the connection without a reply")
        try:
            return json.loads(buf.decode("utf-8", "replace").splitlines()[0])
        except json.JSONDecodeError as e:
            raise BridgeError(f"unparseable reply: {buf[:200]!r}") from e

    # ---- convenience
    def ping(self) -> dict:
        return self.call("ping")

    def info(self) -> dict:
        return self.call("info")

    def eval(self, code: str = "", expr: str = "None", timeout: float | None = None) -> dict:
        old = self.timeout
        if timeout:
            self.timeout = timeout
        try:
            return self.call("eval", code=code, expr=expr)
        finally:
            self.timeout = old

    def shutdown(self) -> dict:
        return self.call("shutdown")
