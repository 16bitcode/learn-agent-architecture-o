from loop import final_text, run_tool, run_turn


class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Msg:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason


def test():
    assert run_tool("get_time", {}).startswith("20")
    assert run_tool("nope", {}).startswith("error")
    assert final_text(_Msg([_Text("hi")])) == "hi"

    seen = {}

    def model(messages):
        seen["count"] = len(messages)
        return _Msg([_Text(f"reply {len(messages)}")])

    messages = []
    messages.append({"role": "user", "content": "first"})
    assert run_turn(messages, model) == "reply 1"
    assert len(messages) == 2

    messages.append({"role": "user", "content": "second"})
    run_turn(messages, model)
    assert seen["count"] == 3
    assert messages[0]["content"] == "first"

    print("01 agent_loop: ok")


if __name__ == "__main__":
    test()
