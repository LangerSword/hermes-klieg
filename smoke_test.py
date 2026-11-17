"""Smoke test for the job engine and the Blender adapter.

Run: python3 smoke_test.py
No plugin host needed - klieg_core and klieg_adapters are plain modules.
"""

import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import klieg_core as core
import klieg_adapters as A


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="klieg-smoke-")
    artefact = os.path.join(tmp, "frame_0000.png")

    print("1. detached job writes an artefact")
    j = core.launch("smoke", ["/bin/sh", "-c", f"sleep 1; echo done > {artefact}"],
                    guard=[artefact], what="smoke: one frame")
    print("   launched", j["job"], "pid", j["pid"])
    time.sleep(3)
    st = core.poll(j["job"])
    print("   state", st.get("state"), "exit", st.get("exit"))
    v = core.verify(j["job"])
    print("   verify ok:", v["ok"], "artefacts:", len(v["artefacts"]), "missing:", len(v["missing"]))
    assert st.get("state") == "done" and v["ok"], "detached job did not verify"

    print("2. stale artefact is caught")
    old = os.path.join(tmp, "old.png")
    open(old, "w").close()
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    j2 = core.launch("stale", ["/bin/sh", "-c", "true"], guard=[old], what="stale check")
    time.sleep(1.5)
    v2 = core.verify(j2["job"])
    print("   verify ok:", v2["ok"], "stale:", len(v2["stale"]), "missing:", len(v2["missing"]))
    assert not v2["ok"] and v2["stale"], "stale artefact was NOT caught"

    print("3. failing job records its exit code")
    j3 = core.launch("fail", ["/bin/sh", "-c", "exit 7"], what="failure")
    time.sleep(1.5)
    st3 = core.poll(j3["job"])
    print("   state", st3.get("state"), "exit", st3.get("exit"))
    assert st3.get("state") == "failed" and st3.get("exit") == 7, "exit code lost"

    print("4. GPU lock refuses a second render")
    core._take_lock("smoke-gpu", "holder", os.getpid())
    held = core.gpu_busy("smoke-gpu")
    print("   busy:", bool(held), "held_by:", (held or {}).get("job"))
    core.release_lock("smoke-gpu", "holder")
    print("   after release, busy:", bool(core.gpu_busy("smoke-gpu")))
    assert held and not core.gpu_busy("smoke-gpu")

    print("5. adapter probe")
    for a in A.ADAPTERS.values():
        d = a.detect()
        print(f"   {a.name:9s} found={d.get('found')} {d.get('version', '')[:48]}")

    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
