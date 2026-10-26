"""
智能体循环（第 2 节）：通过工具注册表（Registry）进行分发。

相较于第 1 节的改动：内联工具被移入一个注册表（`tools.py`）中，
每个 `tool_use` 代码块均通过 `_dispatch` 进行路由分发。
`run()` 函数接收一个 `registry` 参数，该注册表也会被传递给模型，以便模型能够展示其可用的工具架构（schemas）。
循环主体部分沿用了第 1 节中基于 Anthropic Messages 格式的 `while` 循环。
在第 3 节和第 4 节中，`_dispatch` 将进一步扩展，加入权限控制机制（permission gate）和钩子（hooks）。
"""

from __future__ import annotations

from tools import Registry, run_tool


def run_turn(messages, model, registry: Registry, max_steps=10):
    for _ in range(max_steps):
        response = model(messages, registry)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return final_text(response)

        results = [
            _dispatch(b, registry) for b in response.content if b.type == "tool_use"
        ]
        messages.append({"role": "user", "content": results})

    raise RuntimeError("hit max_steps without end_turn")


def _dispatch(block, registry):
    """解析 tool_use 代码块，运行它，并将输出封装为 tool_result。
    第 3 节和第 4 节将扩展此函数。"""
    tool = registry.get(block.name)
    content = (
        f"error: no tool {block.name!r}"
        if tool is None
        else run_tool(tool, block.input)
    )
    return {"type": "tool_result", "tool_use_id": block.id, "content": content}


def final_text(response):
    """模型的最后指令：连接其文本块。"""
    return "".join(b.text for b in response.content if b.type == "text")
