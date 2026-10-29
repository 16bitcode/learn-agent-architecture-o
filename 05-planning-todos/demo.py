import os

from anthropic import Anthropic
from dotenv import load_dotenv
from loop import Session, run_turn
from permissions import DEFAULT
from planning import todo_tool
from tools import Registry

load_dotenv(override=True)

SYSTEM = "You are a tiny agent. Use the provided tools to answer. Be brief."
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

    session = Session(mode=DEFAULT)
    reg = Registry()
    reg.registry(todo_tool(session))

    answer = run_turn(
        [
            {
                "role": "user",
                "content": "列出一份包含两个步骤的厨房清洁待办清单，然后说“完成”。",
            }
        ],
        model,
        reg,
        session,
    )

    print("05 planning -> ", answer, "| todos:", len(session.todos))


if __name__ == "__main__":
    demo()
