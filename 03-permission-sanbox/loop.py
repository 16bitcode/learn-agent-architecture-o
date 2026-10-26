from __future__ import annotations

import permissions
from tools import Registry, run_tool


def run_turn(
    messages,
    model,
    registry: Registry,
    mode=permissions.DEFAULT,
    allow_rules=None,
    approver=None,
    max_steps=10,
):
    allow_rules = allow_rules or set()
    approver = approver or (lambda name, args: False)

    for _ in range(max_steps):
        response = model(messages, registry)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return final_text(response)

        results = [
            _dispatch(b, registry, mode, allow_rules, approver)
            for b in response.content
            if b.type == "tool_use"
        ]
        messages.append({"role": "user", "content": results})
        
    raise RuntimeError('hit max_steps')


def _dispatch(block, registry, mode, allow_rules, approver):
