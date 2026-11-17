"""Approval policy for Klieg.

Three of these tools execute model-authored Python inside another application,
and two of them spend GPU time or overwrite deliverables. All of them go to the
human gate; probing and inspecting do not. Unattended runs fail closed.
"""

from __future__ import annotations

import json

EXECUTING = frozenset({"klieg_run", "klieg_track", "klieg_gate", "klieg_render", "klieg_publish"})
READ_ONLY = frozenset({"klieg_probe", "klieg_scene", "klieg_plan"})
JOBS_SAFE = frozenset({"list", "status", "log", "verify"})


def _detail(tool_name: str, args: dict) -> str:
    if tool_name == "klieg_run":
        return f"{args.get('dcc', 'blender')} <- {args.get('script', '')}"
    if tool_name in {"klieg_track", "klieg_gate"}:
        return f"{args.get('dcc', 'blender')} <- {args.get('script', '')}"
    if tool_name == "klieg_render":
        return (f"{args.get('dcc', 'blender')} frames {args.get('frames', '?')} "
                f"-> {args.get('outdir', '?')}")
    if tool_name == "klieg_publish":
        return f"{args.get('frames_dir', '?')} -> {args.get('out', '?')}"
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
    if tool_name in EXECUTING:
        return {"action": "approve", "message": f"{tool_name}: {_detail(tool_name, args)}".strip(),
                "rule_key": f"klieg:{tool_name}"}
    return None


__all__ = ["pre_tool_call", "EXECUTING", "READ_ONLY"]
