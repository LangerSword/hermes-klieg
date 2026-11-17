"""Prove the live bridge against a real Blender, headless.

    <venv>/python scripts/test_bridge.py

Launches Blender with blender/klieg_headless_server.py on a temp socket, then drives it
through the same Bridge class the tool uses: ping, info, an eval that mutates the scene,
an eval that raises (the error must come back as data, not a hang), then shutdown.
Prints PASS/FAIL per step.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from klieg_bridge import Bridge, BridgeTimeout, BridgeUnavailable, default_socket

SERVER = os.path.join(REPO, "blender/klieg_headless_server.py")
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name:34s} {detail}")


def main() -> int:
    sock = os.path.join(tempfile.mkdtemp(prefix="klieg-bridge-"), "b.sock")
    env = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")}
    proc = subprocess.Popen(
        ["/usr/bin/blender", "-b", "--factory-startup", "--python", SERVER, "--", sock],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
        start_new_session=True)

    deadline = time.time() + 90
    while time.time() < deadline and not os.path.exists(sock):
        if proc.poll() is not None:
            break
        time.sleep(0.3)
    check("blender started and bound the socket", os.path.exists(sock), sock)

    if not os.path.exists(sock):
        out = proc.stdout.read()[-600:] if proc.stdout else ""
        print(out)
        proc.kill()
        return 1

    b = Bridge(sock, timeout=30)
    try:
        r = b.ping()
        check("ping", r.get("ok") and r.get("result") == "pong", str(r.get("result")))

        r = b.info()
        info = json.loads(r["result"])
        before = int(info.get("objects", 0))
        check("info reports a real Blender", info.get("blender", "").startswith("5."),
              f"{info.get('blender')} objects={before} vt={info.get('view_transform')}")

        r = b.eval(code="bpy.ops.mesh.primitive_cube_add(size=2)",
                   expr="len(bpy.data.objects)")
        check("eval mutates the scene", r.get("ok") and r.get("result") == str(before + 1),
              f"{r.get('result')} (was {before})")

        r = b.eval(code="", expr="bpy.context.scene.view_settings.view_transform")
        check("reads colour management", r.get("ok") and len(r.get("result", "")) > 2,
              str(r.get("result")))

        r = b.eval(code="raise ValueError('boom')", expr="1")
        check("error comes back as data", r.get("ok") is False and "boom" in r.get("error", ""),
              "ValueError surfaced")

        r = b.eval(code="", expr="bpy.context.scene.render.fps")
        check("session survives a failed call", r.get("ok"), str(r.get("result")))

        t0 = time.time()
        r = b.shutdown()
        check("shutdown acknowledged", r.get("ok"), f"{time.time() - t0:.2f}s")
    except (BridgeTimeout, BridgeUnavailable) as e:
        check("bridge transport", False, f"{type(e).__name__}: {e}")
    finally:
        proc.wait(timeout=20)

    check("process exited after shutdown", proc.returncode is not None,
          str(proc.returncode))
    check("socket removed on exit", not os.path.exists(sock))

    ok = all(r[1] for r in results)
    print(f"\n{sum(1 for r in results if r[1])}/{len(results)} passed")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
