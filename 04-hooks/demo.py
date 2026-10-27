import os

from anthropic import Anthropic
from dotenv import load_dotenv
from hooks import PRE_TOOL_USE, Hooks
from loop import run_turn
from permissions import BYPASS
from tools import Registry, Tool

load_dotenv(override=True)

SYSTEM = "你是一个小agent。请使用提供的工具作答。务必言简意赅。"
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
            "Bash",
            lambda a: "ran",
            description="执行一个shell命令",
            input_schema={
                "type": "object",
                "properties": {"command": {"type": "string"}, "required": ["command"]},
            },
        )
    )

    hooks = Hooks()
    hooks.on(
        PRE_TOOL_USE,
        lambda n, a: (
            {"deny": True, "message": "refusing rm -rf"}
            if n == "Bash" and "rm -rf" in a.get("command", "")
            else None
        ),
    )

    answer = run_turn(
        [{"role": "user", "content": "Run the shell command: echo hello"}],
        model,
        reg,
        hooks=hooks,
        mode=BYPASS,
    )
    print("04 hooks -> ", answer)


if __name__ == "__main__":
    demo()
