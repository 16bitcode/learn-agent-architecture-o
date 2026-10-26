import os

from anthropic import Anthropic
from dotenv import load_dotenv
from loop import run_turn
from tools import Registry, Tool

load_dotenv(override=True)

SYSTEM = "你是一名小助手。请使用提供的工具作答。务必言简意赅。"
MODEL = os.environ.get("MODEL", "kimi-k3")
FILES = {"a.txt": "alpha", "b.txt": "beta"}


def demo():
    if not os.environ.get("API_KEY"):
        print("02 没有提供API_KEY")
        return

    client = Anthropic(
        base_url=os.environ.get("BASE_URL") or None, api_key=os.environ.get("API_KEY")
    )

    def model(messages, registry):
        return client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=registry.schemas(),
            max_tokens=1024,
        )

    reg = Registry()
    reg.registry(
        Tool(
            "ReadFile",
            lambda a: FILES[a["path"]],
            description="通过路径读取文件内容。",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            is_read_only=True,
            is_concurrency_safe=True,
        )
    )
    answer = run_turn(
        [
            {
                "role": "user",
                "content": "读取 a.txt 和 b.txt，然后回复这两个文件的内容。",
            }
        ],
        model,
        reg,
    )
    print("tool runtime ->", answer)


if __name__ == "__main__":
    demo()
