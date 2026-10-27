from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

NO_INPUTS = {"type": "object", "properties": {}}


# 工具类：名称、执行工具方法、描述、输入参数约束、只读、并发安全、编辑
@dataclass
class Tool:
    name: str
    run: Callable[[dict], Any]
    description: str = ""
    input_schema: dict = field(default_factory=lambda: dict(NO_INPUTS))
    is_read_only: bool = False
    is_concurrency_safe: bool = False
    is_edit: bool = False


# 工具注册类
class Registry:
    """将名称映射至工具。添加工具即注册一个处理程序。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def registry(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in self._tools.values()
        ]


# 执行工具
def run_tool(tool: Tool, tool_input: dict) -> str:
    """执行一个工具，并将任何失败转化为字符串结果（绝不会抛出异常）。"""
    try:
        return str(tool.run(tool_input))
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"


# 并发执行工具
def run_concurrently(registry: Registry, calls: list[dict]) -> list[str]:
    """分发单轮中的工具调用；支持并发的操作会被归入同一个并行批次。输出顺序与输入顺序一致。为保证可读性，循环会按顺序进行分发；这正是实际运行时所采用的批处理机制。每个调用均表示为 `{"name": ..., "input": ...}`。"""
    tools = [registry.get(c["name"]) for c in calls]
    out: dict[int, str] = {}

    safe = [i for i, t in enumerate(tools) if t and t.is_concurrency_safe]

    if safe:
        with ThreadPoolExecutor(max_workers=len(safe)) as pool:
            for i, res in zip(
                safe,
                pool.map(lambda i: run_tool(tools[i], calls[i].get("input", {})), safe),
            ):
                out[i] = res

    for i, t in enumerate(tools):
        if i not in out:
            out[i] = (
                f"error: no tool {calls[i]['name']!r}"
                if t is None
                else run_tool(t, calls[i].get("input", {}))
            )

    return [out[i] for i in range(len(calls))]
