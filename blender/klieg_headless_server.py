"""Headless Klieg bridge: a Blender that waits for commands instead of exiting.

    blender -b scene.blend --python klieg_headless_server.py -- /run/user/1000/klieg-123.sock

Why a blocking loop rather than the add-on's timer queue: in `-b` mode Blender exits when
the script returns, and a thread-owned executor cannot touch `bpy` safely. Running the
accept-and-execute loop on the main thread gives one owner for `bpy` and a process that
stays up exactly as long as the socket exists.
"""

import json
import os
import socket
import sys
import traceback

import bpy

SOCKET = None
if "--" in sys.argv:
    rest = sys.argv[sys.argv.index("--") + 1:]
    if rest:
        SOCKET = rest[0]
SOCKET = SOCKET or os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "klieg.sock")


def _exec(code, expr):
    """Execute model-authored code inside Blender. This is the product, not an accident.

    Deliberately unsafe-by-design, and bounded by four things rather than by sanitising
    Python (which is not possible): the socket is a unix domain socket chmod 0600 in the
    user's runtime dir (no network, no other users), the process runs as the user (no
    privilege gain over just opening Blender), every call arrives through the plugin's
    approval-gated tool, and the namespace starts as {"bpy": bpy} so nothing is imported
    implicitly. The same capability is what Blender's own MCP add-on exposes.
    """
    ns = {"bpy": bpy}
    exec(code or "", ns)                      # noqa: S102 - see docstring
    return repr(eval(expr or "None", ns))     # noqa: S307 - see docstring


def serve(path):
    if os.path.exists(path):
        os.unlink(path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    os.chmod(path, 0o600)
    srv.listen(8)
    print(f"KLIIEG_BRIDGE_READY {path}", flush=True)
    stop = False
    while not stop:
        conn, _ = srv.accept()
        try:
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
            req = json.loads(buf.decode("utf-8", "replace") or "{}")
            op = req.get("op")
            if op == "ping":
                res = {"ok": True, "result": "pong"}
            elif op == "info":
                sc = bpy.context.scene
                res = {"ok": True, "result": json.dumps({
                    "blender": bpy.app.version_string,
                    "file": bpy.data.filepath,
                    "objects": len(sc.objects),
                    "view_transform": sc.view_settings.view_transform,
                })}
            elif op == "eval":
                try:
                    res = {"ok": True, "result": _exec(req.get("code"), req.get("expr"))}
                except Exception:
                    res = {"ok": False, "error": traceback.format_exc(limit=3)}
            elif op == "shutdown":
                res = {"ok": True, "result": "bye"}
                stop = True
            else:
                res = {"ok": False, "error": f"unknown op {op!r}"}
            res["id"] = req.get("id", 0)
            conn.sendall((json.dumps(res) + "\n").encode())
        except Exception:
            try:
                conn.sendall((json.dumps({"ok": False, "id": 0,
                                          "error": traceback.format_exc(limit=2)}) + "\n").encode())
            except OSError:
                pass
        finally:
            conn.close()
    srv.close()
    try:
        os.unlink(path)
    except OSError:
        pass


try:
    serve(SOCKET)
except OSError as e:
    print(f"KLIIEG_BRIDGE_FAILED {e}", flush=True)
