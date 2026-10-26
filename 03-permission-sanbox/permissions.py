from __future__ import annotations

from tools import Tool

DEFAULT, ACCEPT_EDITS, PLAN, BYPASS = (
    "default",
    "acceptEdits",
    "plan",
    "bypassPermissions",
)


def decide(tool: Tool, mode: str, allow_rules: set) -> str:
    """返回allow、ask或deny以在mode下运行tool。"""
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
