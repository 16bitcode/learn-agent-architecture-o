from datetime import datetime, timezone


def get_time(_input):
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


TOOL_SCHEMA = [
    {
        "name": "get_time",
        "description": "Return the current UTC time as an ISO 8601 string.",
        "input_schema": {"type": "object", "properties": {}},
    }
]

HANDLERS = {"get_time": get_time}


def run_tool(name, tool_input):
    fn = HANDLERS.get(name)
    if fn is None:
        return f"error: no tool {name!r}"
    try:
        return fn(tool_input)
    except Exception as e:
        return f"error: {e}"


def run_turn(messages, model, max_steps=10):
    for _ in range(max_steps):
        response = model(messages)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return final_text(response)

        results = []
        for block in response.content:
            if block.type == "tool_use":
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": run_tool(block.name, block.input),
                    }
                )
        messages.append({"role": "user", "content": results})

    raise RuntimeError("hit max_steps without end_turn")


def final_text(response):
    return "".join(b.text for b in response.content if b.type == "text")
