#!/usr/bin/env python3
"""No-network check of the OpenAI-compatible tool loop."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.agents import Context, OpenAICompatAgent  # noqa: E402


class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _Call:
    def __init__(self, name, arguments, call_id="call_1"):
        self.id = call_id
        self.function = _Fn(name, arguments)

    def dump(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.function.name, "arguments": self.function.arguments}}


class _Msg:
    def __init__(self, content=None, tool_calls=None, reasoning=""):
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning = reasoning

    def model_dump(self, exclude_none=True):
        data = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = [c.dump() for c in self.tool_calls]
        return data


class _Choice:
    def __init__(self, message):
        self.message = message


class _Resp:
    def __init__(self, message):
        self.choices = [_Choice(message)]


class _Stub:
    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    class completions:
        pass

    def __init_client(self):
        pass


class StubClient:
    def __init__(self, script, fail_times=0):
        self.script = list(script)
        self.fail_times = fail_times
        self.calls = 0
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls += 1
        if self.fail_times:
            self.fail_times -= 1
            err = RuntimeError("busy")
            err.status_code = 503
            raise err
        if not self.script:
            raise AssertionError("model kept calling")
        return _Resp(self.script.pop(0))


def main():
    seen = {}

    def fhir_search(resource_type, params=None):
        seen["search"] = (resource_type, params)
        return {"total": 0, "entry": []}

    ctx = Context(task={}, system="sys", instruction="look up the patient", subject="pt-001",
                  tools={"fhir_search": fhir_search})
    script = [
        _Msg(tool_calls=[_Call("fhir_search", '{"resource_type":"Patient","params":{"patient":"pt-001"}}')]),
        _Msg(content="<think>hidden</think>HbA1c is 6.7", reasoning="channel"),
    ]
    client = StubClient(script, fail_times=1)
    agent = OpenAICompatAgent("stub", "http://example/v1", client=client, seed=1)
    answer = agent.run(ctx)
    assert answer == "HbA1c is 6.7", answer
    assert "hidden" in agent.last_reasoning
    assert seen["search"][0] == "Patient"
    assert client.calls == 3  # one 503, then tool, then answer

    def boom(**kwargs):
        raise AssertionError("tool should not run")

    bad = StubClient([
        _Msg(tool_calls=[_Call("fhir_search", "not-json", "call_bad")]),
        _Msg(content="stopped"),
    ])
    agent2 = OpenAICompatAgent("stub", "http://example/v1", client=bad)
    agent2.run(Context(task={}, system="s", instruction="i", subject="pt-001", tools={"fhir_search": boom}))
    print("stub loop OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
