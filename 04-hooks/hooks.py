from __future__ import annotations

PRE_TOOL_USE, POST_TOOL_USE = "PreToolUse", "PostToolUse"


class Hooks:
    def __init__(self):
        self._hooks = {PRE_TOOL_USE: [], POST_TOOL_USE: []}

    def on(self, event, fn):
        callbacks = self._hooks.setdefault(event, [])
        if fn in callbacks:
            callbacks.append(callbacks.pop(callbacks.index(fn)))
        else:
            callbacks.append(fn)

    def fire_pre(self, name, args):
        for fn in self._hooks[PRE_TOOL_USE]:
            out = fn(name, args) or {}
            if out.get("updated_args"):
                args = out["updated_args"]
            if out.get("deny"):
                return True, args, out.get("message", "blocked by hook")

        return False, args, ""

    def fire_post(self, name, args, result):
        for fn in self._hooks[POST_TOOL_USE]:
            fn(name, args, result)
