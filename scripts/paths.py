"""Shared input-path resolution for the demo and e2e scripts.

Default to the repo fixture, never the author's machine. Override with
KLIEG_BLEND (a blend file) or KLIEG_FILM (a rendered frame directory).
"""

import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_BLEND = os.path.join(REPO, "fixtures", "cube.blend")
FIXTURE_FILM = os.path.join(REPO, "fixtures", "frames")


def resolve_input(kind: str, cli_value: str | None = None) -> str:
    """Resolve blend/film path: CLI first, then env, then repo fixture."""
    env_key = "KLIEG_BLEND" if kind == "blend" else "KLIEG_FILM"
    path = cli_value or os.environ.get(env_key)
    if path:
        path = os.path.abspath(os.path.expanduser(path))
    else:
        path = FIXTURE_BLEND if kind == "blend" else FIXTURE_FILM
    if not os.path.exists(path):
        raise SystemExit(
            f"{kind} not found: {path}\n"
            f"Set {env_key} or pass the path as an argument. "
            f"The repo default is {FIXTURE_BLEND if kind == 'blend' else FIXTURE_FILM}."
        )
    return path
