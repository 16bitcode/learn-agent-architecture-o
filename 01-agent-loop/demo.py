import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from loop import TOOL_SCHEMA, run_turn

load_dotenv(Path(__file__).with_name(".env"), override=True)

SYSTEM = "你是一个微型智能体。请使用所提供的工具进行回答。言简意赅。"
MODEL = os.environ.get("MODEL", "kimi-k3")

TURNS = [
    "现在是什么时间？请用一句话回答。",
    "那是 UTC 时间的中午之前，还是之后？",
]


def demo():
    api_key = os.environ.get("API_KEY")
    if not api_key:
        print("请在 .env 中设置 API_KEY")
        return

    client = Anthropic(
        api_key=api_key,
        base_url=os.environ.get("BASE_URL") or None,
    )

    def model(messages):
        return client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOL_SCHEMA,
            max_tokens=1024,
        )

    messages = []
    for user_text in TURNS:
        messages.append({"role": "user", "content": user_text})
        reply = run_turn(messages, model)
        print("You ->", user_text)
        print("agent loop ->", reply)


if __name__ == "__main__":
    demo()
