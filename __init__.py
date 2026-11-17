"""Klieg: a DCC bridge for Hermes.

One adapter interface over the tools that make pictures. The plugin's job is not
to know Blender - it is to make long GPU work survivable: detached jobs with
logfiles and exit codes, artefact mtime guards, and measurements instead of
claims.

Wiring uses the public plugin API: ctx.register_tool / ctx.register_hook.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__version__ = "0.1.0"

TOOLSET = "klieg"


def register(ctx) -> None:
    from .klieg_hooks import pre_tool_call
    from .klieg_tools import TOOL_SPECS

    ctx.register_hook("pre_tool_call", pre_tool_call)

    for spec in TOOL_SPECS:
        def tool_handler(args: dict, _run=spec["handler"], **_kw) -> str:
            return _run(args or {})

        ctx.register_tool(
            name=spec["name"],
            toolset=TOOLSET,
            schema=spec["schema"],
            handler=tool_handler,
            description=spec["description"],
            emoji=spec.get("emoji", "🎬"),
        )


__all__ = ["register", "__version__"]
