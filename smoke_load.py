"""Served-surface smoke: load the plugin the way the host does, then prove it.

Run: python3 smoke_load.py
No plugin host, no numpy/Pillow, no Blender needed. Where smoke_test.py exercises
the job ENGINE, this exercises the SURFACE: it loads __init__.py as a package with
relative imports, calls register() against a recording context, and checks that

  - every declared tool actually registers (14), and the one hook registers,
  - the registered pre_tool_call callback approves executing verbs and passes
    read-only ones, per action, when dispatched with real payloads,
  - a registered handler answers as data (an error object), never a traceback.

This is the smallest real load+registration+dispatch proof: validate/doctor run
register() in isolation, but only this drives the registered hook and a handler.
"""

import importlib.util
import json
import os
import sys
import tempfile

# Hermetic: a fresh data dir so no real job/history can change an assertion.
os.environ["HERMES_PLUGIN_DATA"] = tempfile.mkdtemp(prefix="klieg-load-smoke-")
REPO = os.path.dirname(os.path.abspath(__file__))


def load_plugin():
    spec = importlib.util.spec_from_file_location(
        "klieg", os.path.join(REPO, "__init__.py"),
        submodule_search_locations=[REPO])
    assert spec is not None and spec.loader is not None, "cannot load plugin entry point"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["klieg"] = mod
    spec.loader.exec_module(mod)
    return mod


class RecordingCtx:
    def __init__(self):
        self.tools = {}
        self.hooks = []

    def register_tool(self, name, toolset, schema, handler, description, emoji=None):
        self.tools[name] = handler

    def register_hook(self, name, fn):
        self.hooks.append((name, fn))


def main() -> int:
    mod = load_plugin()
    ctx = RecordingCtx()
    mod.register(ctx)

    print("version:", mod.__version__)
    print("registered tools:", len(ctx.tools), sorted(ctx.tools))
    print("registered hooks:", [h[0] for h in ctx.hooks])
    assert len(ctx.tools) == 14, f"expected 14 tools, got {len(ctx.tools)}"
    assert [h[0] for h in ctx.hooks] == ["pre_tool_call"], "hook mismatch"

    hook = ctx.hooks[0][1]
    cases = [
        ("klieg_render", {"blend": "s.blend", "frames": "0-1", "outdir": "/tmp/x"}, "approve"),
        ("klieg_probe", {}, None),
        ("klieg_gate", {"gate": "flash", "frames_dir": "/tmp/x"}, None),
        ("klieg_gate", {"script": "m.py"}, "approve"),
        ("klieg_session", {"action": "status"}, None),
        ("klieg_session", {"action": "eval", "code": "x"}, "approve"),
        ("klieg_ledger", {"action": "check", "job": "j"}, None),
        ("klieg_ledger", {"action": "seal", "job": "j"}, "approve"),
        ("klieg_motion", {"action": "templates"}, None),
        ("klieg_motion", {"action": "render", "template": "title-reveal", "out": "/tmp/x.mp4"}, "approve"),
    ]
    for tool, args, want in cases:
        got = hook(tool, args)
        action = got.get("action") if isinstance(got, dict) else None
        print(f"hook {tool:14s} {json.dumps(args):48s} -> {action}")
        assert action == want, f"{tool} {args}: expected {want}, got {action}"

    out = json.loads(ctx.tools["klieg_ledger"]({"action": "check", "job": "no-such-job"}))
    print("klieg_ledger check(no-such-job) ->", json.dumps(out))
    assert out["ok"] is False and "no ledger" in out["error"], "handler did not answer as data"

    mt = json.loads(ctx.tools["klieg_motion"]({"action": "templates"}))
    print("klieg_motion templates ->", [t["name"] for t in mt["templates"]])
    assert any(t["name"] == "title-reveal" for t in mt["templates"]), "motion templates missing"

    print("\nLOAD SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())