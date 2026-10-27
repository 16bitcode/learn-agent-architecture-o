import os

from anthropic import Anthropic
from dotenv import load_dotenv
from loop import run_turn
from permissions import DEFAULT
from tools import Registry, Tool

load_dotenv(override=True)

SYSTEM = "你是一个微型智能体。请使用所提供的工具进行回答。言简意赅。"
MODEL = os.environ.get("MODEL", "kimi-k3")

client = Anthropic(
    base_url=os.environ.get("BASE_URL"), api_key=os.environ.get("API_KEY")
)


def demo():
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
            lambda a: "data",
            description="根据路径读取文件。",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            is_read_only=True,
        )
    )

    answer = run_turn(
        [{"role": "user", "content": "读取文件 a.txt 并总结它"}],
        model,
        reg,
        mode=DEFAULT,
    )

    print("permissions -> ", answer)


if __name__ == "__main__":
    demo()
