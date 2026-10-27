from __future__ import annotations

DEFAULT, ACCEPT_EDITS, PLAN, BYPASS = (
    "default",
    "acceptEdits",
    "plan",
    "bypassPermissions",
)


def decide(tool, mode: str, allow_rules: set) -> str:
    """return allow, ask, deny for running tool under mode"""
    if mode == BYPASS:
        return "allow"

    if mode == PLAN:
        if tool.is_read_only:
            return "allow"
        if tool.name == "ExitPlanMode":
            return "ask"
        return "deny"

    if tool.is_read_only or tool.name in allow_rules:
        return "allow"

    if mode == ACCEPT_EDITS and tool.is_edit:
        return "allow"

    return "ask"
