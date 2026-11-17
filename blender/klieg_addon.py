"""Klieg bridge, Blender add-on.

Install: Preferences > Add-ons > Install from Disk > this file, then tick it. The panel is in
the 3D View sidebar under "Klieg". Start Bridge opens a unix socket in the user's runtime
directory; the plugin connects to it with klieg_session.

Why a queue and a timer: `bpy` is not thread-safe, so sockets cannot execute anything from
their own thread. Connections are handled on a background thread which only parses JSON and
parks the request in a queue; `bpy.app.timers` drains that queue on the main thread and hands
the reply back through an Event. That keeps one owner for `bpy`, which is the only version of
this that does not intermittently segfault the UI.

Security: the socket is created with mode 0600 in this user's runtime directory, is never a
TCP port, and executes at the privileges Blender already has. Starting the bridge is therefore
equivalent to leaving Blender open; it grants nothing that opening a .blend and running a
script would not.
"""

bl_info = {
    "name": "Klieg bridge",
    "author": "Lakshaya Sharma (LangerSword)",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "3D View > Sidebar > Klieg",
    "description": "Expose this session to the Hermes Klieg plugin over a unix socket",
    "category": "System",
}

import json
import os
import queue
import socket
import threading
import traceback

import bpy

_QUEUE: "queue.Queue" = queue.Queue()
_STATE = {"thread": None, "server": None, "path": None, "running": False}
_TIMER = None


def _drain():
    """Main thread: execute whatever the socket thread parked, signal the waiter."""
    while True:
        try:
            job = _QUEUE.get_nowait()
        except queue.Empty:
            break
        try:
            ns = {"bpy": bpy}
            exec(job["code"] or "", ns)                 # noqa: S102 - the add-on's purpose
            job["result"] = repr(eval(job["expr"] or "None", ns))   # noqa: S307
            job["ok"] = True
        except Exception:
            job["ok"] = False
            job["error"] = traceback.format_exc(limit=3)
        job["event"].set()
    return 0.05


def _serve(path, stop_event):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    if os.path.exists(path):
        os.unlink(path)
    srv.bind(path)
    os.chmod(path, 0o600)
    srv.listen(4)
    srv.settimeout(0.2)
    _STATE["server"] = srv
    while not stop_event.is_set():
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break
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
                job = {"code": req.get("code", ""), "expr": req.get("expr", "None"),
                       "event": threading.Event(), "ok": False, "result": None}
                _QUEUE.put(job)
                if not job["event"].wait(timeout=30):
                    res = {"ok": False, "error": "main thread did not answer within 30s"}
                else:
                    res = {"ok": job["ok"]}
                    if job["ok"]:
                        res["result"] = job["result"]
                    else:
                        res["error"] = job["error"]
            elif op == "shutdown":
                res = {"ok": True, "result": "bye"}
                stop_event.set()
            else:
                res = {"ok": False, "error": f"unknown op {op!r}"}
            res["id"] = req.get("id", 0)
            try:
                conn.sendall((json.dumps(res) + "\n").encode())
            except OSError:
                pass
        except Exception:
            pass
        finally:
            conn.close()
    srv.close()
    try:
        os.unlink(path)
    except OSError:
        pass


def _mkpath():
    base = bpy.app.tempdir or os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(base, "klieg.sock")


class KLIEG_OT_start(bpy.types.Operator):
    bl_idname = "klieg.start_bridge"
    bl_label = "Start Bridge"
    bl_description = "Open a unix socket so the Klieg plugin can drive this session"

    def execute(self, context):
        global _TIMER
        if _STATE["running"]:
            self.report({"INFO"}, "already running at " + str(_STATE["path"]))
            return {"CANCELLED"}
        path = _mkpath()
        stop = threading.Event()
        th = threading.Thread(target=_serve, args=(path, stop), daemon=True)
        th.start()
        _STATE.update(thread=th, path=path, running=True, stop=stop)
        _TIMER = bpy.app.timers.register(_drain, first_interval=0.05, persistent=True)
        self.report({"INFO"}, "Klieg bridge listening on " + path)
        return {"FINISHED"}


class KLIEG_OT_stop(bpy.types.Operator):
    bl_idname = "klieg.stop_bridge"
    bl_label = "Stop Bridge"
    bl_description = "Close the socket"

    def execute(self, context):
        global _TIMER
        if not _STATE["running"]:
            return {"CANCELLED"}
        _STATE["stop"].set()
        _STATE["thread"].join(timeout=3)
        _STATE.update(running=False)
        if _TIMER:
            try:
                bpy.app.timers.unregister(_drain)
            except ValueError:
                pass
            _TIMER = None
        self.report({"INFO"}, "Klieg bridge stopped")
        return {"FINISHED"}


class KLIEG_PT_panel(bpy.types.Panel):
    bl_label = "Klieg"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Klieg"

    def draw(self, context):
        col = self.layout.column()
        if _STATE["running"]:
            col.label(text="listening: " + os.path.basename(str(_STATE["path"])))
            col.operator("klieg.stop_bridge", icon="PAUSE")
        else:
            col.label(text="bridge stopped")
            col.operator("klieg.start_bridge", icon="PLAY")


CLASSES = (KLIEG_OT_start, KLIEG_OT_stop, KLIEG_PT_panel)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    if _STATE["running"]:
        _STATE["stop"].set()
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
