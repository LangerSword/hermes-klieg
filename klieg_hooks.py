"""Approval policy for Klieg.

Verbs that execute model-authored Python inside another application, spend GPU
time, or overwrite deliverables go to the human gate. Read-only actions of a
mixed tool do not: klieg_session status/list/colour and klieg_colour
probe/compare/tags inspect; start/eval/stop and write mutate. Unattended runs
fail closed.

A prompt must show everything the approval authorizes: the FULL eval code and
expr (a truncated prefix can hide the rest), and the resolved destination of
every write, via the same resolvers the handlers use.
"""

from __future__ import annotations

import json

try:  # loaded as a Hermes plugin package
    from . import klieg_tools as tools
except ImportError:  # loaded standalone (tests, scripts)
    import klieg_tools as tools

EXECUTING = frozenset({"klieg_run", "klieg_track", "klieg_gate", "klieg_render", "klieg_publish"})
READ_ONLY = frozenset({"klieg_probe", "klieg_scene", "klieg_plan", "klieg_taste"})
JOBS_SAFE = frozenset({"list", "status", "log", "verify"})
SESSION_SAFE = frozenset({"status", "list", "colour"})
COLOUR_SAFE = frozenset({"probe", "compare", "tags"})
LEDGER_SAFE = frozenset({"check", "show"})
MOTION_SAFE = frozenset({"templates"})


def _detail(tool_name: str, args: dict) -> str:
    if tool_name in {"klieg_run", "klieg_gate"}:
        return f"{args.get('dcc', 'blender')} <- {args.get('script', '')}"
    if tool_name == "klieg_track":
        out = args.get("out")
        dest = f" -> {tools.resolve_write_path(out)}" if out else ""
        return f"{args.get('dcc', 'blender')} <- {args.get('script', '')}{dest}"
    if tool_name == "klieg_render":
        outdir = args.get("outdir")
        dest = tools.resolve_write_path(outdir) if outdir else "?"
        return (f"{args.get('dcc', 'blender')} frames {args.get('frames', '?')} "
                f"-> {dest}")
    if tool_name == "klieg_publish":
        return f"{args.get('frames_dir', '?')} -> {args.get('out', '?')}"
    if tool_name == "klieg_session":
        action = args.get("action", "?")
        target = args.get("socket") or args.get("blend") or ""
        if action == "eval":
            # Full code and expr, never a prefix: the user must see everything
            # that will run before approving it.
            code = str(args.get("code", ""))
            expr = str(args.get("expr", ""))
            msg = f"eval on {target or 'the live session'}: {code}"
            if expr:
                msg += f"\nexpr: {expr}"
            return msg
        return f"{action} {target}".strip()
    if tool_name == "klieg_colour":
        return f"write manifest into {args.get('into') or 'the blend directory'}"
    return json.dumps(args, ensure_ascii=False)[:300]


def pre_tool_call(tool_name: str, args: dict | None = None, **_kwargs):
    args = args if isinstance(args, dict) else {}
    if tool_name in READ_ONLY:
        return None
    if tool_name == "klieg_jobs":
        if str(args.get("action") or "list").lower() in JOBS_SAFE:
            return None
        return {"action": "approve", "message": f"klieg_jobs: {args.get('action')} {args.get('job', '')}".strip(),
                "rule_key": "klieg:klieg_jobs"}
    if tool_name == "klieg_session":
        if str(args.get("action") or "status").lower() in SESSION_SAFE:
            return None
        return {"action": "approve", "message": f"klieg_session: {_detail(tool_name, args)}",
                "rule_key": "klieg:klieg_session"}
    if tool_name == "klieg_colour":
        if str(args.get("action") or "probe").lower() in COLOUR_SAFE:
            return None
        return {"action": "approve", "message": f"klieg_colour: {_detail(tool_name, args)}",
                "rule_key": "klieg:klieg_colour"}
    if tool_name == "klieg_ledger":
        if str(args.get("action") or "show").lower() in LEDGER_SAFE:
            return None
        return {"action": "approve",
                "message": f"klieg_ledger: seal job {args.get('job', '')} (hashes inputs and outputs)",
                "rule_key": "klieg:klieg_ledger"}
    if tool_name == "klieg_motion":
        # render/preview execute model-authored HTML+JS and spawn a renderer;
        # templates only lists starters.
        if str(args.get("action") or "templates").lower() in MOTION_SAFE:
            return None
        return {"action": "approve",
                "message": f"klieg_motion: {args.get('action')} {args.get('template') or 'scene'} "
                           f"-> {tools.resolve_motion_out(args)}",
                "rule_key": "klieg:klieg_motion"}
    if tool_name == "klieg_gate":
        # Built-in gates only read frames and compute numbers: no model-authored
        # code, no GPU, no writes. Script gates still execute code and prompt.
        if args.get("gate") and not args.get("script"):
            return None
        return {"action": "approve", "message": f"klieg_gate: {_detail(tool_name, args)}",
                "rule_key": "klieg:klieg_gate"}
    if tool_name in EXECUTING:
        return {"action": "approve", "message": f"{tool_name}: {_detail(tool_name, args)}".strip(),
                "rule_key": f"klieg:{tool_name}"}
    return None


__all__ = ["pre_tool_call", "EXECUTING", "READ_ONLY"]