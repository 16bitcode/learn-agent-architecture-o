from __future__ import annotations

import permissions
from tools import Tool

TODOS_SCHEMA = {
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step": {
                        "type": "string",
                    },
                    "status": {"type": "string"},
                },
                "required": ["step", "status"],
            },
        }
    },
    "required": ["todos"],
}


def todo_tool(session) -> Tool:
    def write(a):
        session.todos = list(a["todos"])
        done = sum(1 for t in session.todos if t.get("status") == "completed")
        return f"{len(session.todos)} todos ({done}) done"

    return Tool(
        "TodoWrite",
        write,
        description="Record the plan as a checklist of {step, status} items.",
        input_schema=TODOS_SCHEMA,
        is_read_only=True,
    )


def exit_plan_mode_tool(session, to_mode=permissions.ACCEPT_EDITS) -> Tool:
    def exit_plan(a):
        session.mode = to_mode
        return f"plan approved, mode now {to_mode}"

    return Tool(
        "ExitPlanMode",
        exit_plan,
        description="Present the plan and leave plan mode once the user approves.",
    )
