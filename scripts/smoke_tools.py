#!/usr/bin/env python3
"""One tool-call request against an OpenAI-compatible server. No grading."""
import argparse
import json
import os
import sys

from openai import OpenAI

TOOL = {
    "type": "function",
    "function": {
        "name": "fhir_search",
        "description": "Search FHIR resources of one type.",
        "parameters": {
            "type": "object",
            "properties": {
                "resource_type": {"type": "string"},
                "params": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["resource_type"],
        },
    },
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key-env", default="OPENAI_API_KEY")
    args = ap.parse_args()
    client = OpenAI(base_url=args.base_url, api_key=os.environ.get(args.api_key_env, "local"))
    resp = client.chat.completions.create(
        model=args.model,
        temperature=0,
        max_tokens=300,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        messages=[{"role": "user", "content": "Call fhir_search for Patient pt-001. Do not answer in prose."}],
        tools=[TOOL],
    )
    msg = resp.choices[0].message
    calls = list(msg.tool_calls or [])
    print(json.dumps({
        "finish_reason": resp.choices[0].finish_reason,
        "content": msg.content,
        "tool_calls": [
            {"name": c.function.name, "arguments": c.function.arguments} for c in calls
        ],
    }, indent=2))
    if not calls:
        sys.exit("no tool call in the response")
    json.loads(calls[0].function.arguments or "{}")
    if calls[0].function.name != "fhir_search":
        sys.exit(f"unexpected tool {calls[0].function.name}")
    print("smoke tool call OK")


if __name__ == "__main__":
    main()
