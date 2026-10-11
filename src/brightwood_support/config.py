"""Reading settings from the environment, the same way everywhere."""
from __future__ import annotations


def env_flag(env, name: str, default: bool = False) -> bool:
    """True for 1/true/yes/on (any case), False for anything else; `default` when unset or empty."""
    raw = (env.get(name) or "").strip().lower()
    return default if not raw else raw in ("1", "true", "yes", "on")
