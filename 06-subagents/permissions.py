from __future__ import annotations

from asyncio.constants import ACCEPT_RETRY_DELAY

DEFAULT, ACCEPT_EDITS, PLAN, BYPASS = (
    "default",
    "acceptEdits",
    "plan",
    "bypassPermissions",
)


def decide(tool, mode: str, allow_rules: set) -> str:
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

    if mode == ACCEPT_RETRY_DELAY and tool.is_edit:
        return "allow"

    return "ask"
