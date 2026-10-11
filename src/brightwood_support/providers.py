"""A real model provider: Google Gemini over plain HTTPS (standard library only).

It turns our conversation (messages, tool calls, tool results) into Gemini's
request format and the reply back into our Reply. It plugs into the gateway like
any other model.

STATUS: tested only against a fake HTTP function. It has NOT been run against the
real Gemini service, so field names and the model id may need a small fix on the
first real call. The model id and API key come from the environment, never code.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Callable

from .agent import Reply, ToolCall

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
Post = Callable[[str, dict, dict], dict]


def http_post(url: str, headers: dict, body: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise ConnectionError(f"Gemini returned HTTP {error.code}: {error.read()[:200]!r}") from None


def _declarations(tool_specs: list[dict]) -> list[dict]:
    out = []
    for spec in tool_specs:
        types = spec.get("types", {})
        out.append({
            "name": spec["name"],
            "description": spec["description"],
            "parameters": {
                "type": "OBJECT",
                "properties": {p: {"type": types.get(p, "string").upper()} for p in spec["params"]},
                "required": list(spec["params"]),
            },
        })
    return out


def to_gemini(messages: list[dict]) -> tuple[str, list[dict]]:
    """Split our messages into (system text, Gemini contents)."""
    system, contents, names = "", [], {}
    for m in messages:
        role = m["role"]
        if role == "system":
            system = m["content"]
        elif role == "user":
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})
        elif role == "assistant":
            parts = [{"text": m["content"]}] if m.get("content") else []
            for call in m.get("tool_calls", []):
                names[call.id] = call.name
                parts.append({"functionCall": {"name": call.name, "args": call.args}})
            contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            part = {"functionResponse": {"name": names.get(m["tool_call_id"], "unknown"), "response": {"result": m["content"]}}}
            if contents and contents[-1]["role"] == "user" and "functionResponse" in contents[-1]["parts"][0]:
                contents[-1]["parts"].append(part)  # several results go in one turn
            else:
                contents.append({"role": "user", "parts": [part]})
    return system, contents


class GeminiModel:
    def __init__(self, model: str | None = None, api_key: str | None = None, post: Post = http_post) -> None:
        self.model = model or os.environ.get("GEMINI_MODEL", "")
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._post = post
        self._counter = 0

    def next(self, messages: list[dict], tool_specs: list[dict]) -> Reply:
        if not self.model or not self._api_key:
            raise ConnectionError("GEMINI_MODEL and GEMINI_API_KEY must be set")
        system, contents = to_gemini(messages)
        body = {"contents": contents, "tools": [{"functionDeclarations": _declarations(tool_specs)}]}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        data = self._post(URL.format(model=self.model), {"x-goog-api-key": self._api_key}, body)
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            raise ConnectionError(f"unexpected Gemini reply: {str(data)[:200]}") from None
        tokens = int(data.get("usageMetadata", {}).get("totalTokenCount", 0))
        calls, texts = [], []
        for part in parts:
            if "functionCall" in part:
                self._counter += 1
                fc = part["functionCall"]
                calls.append(ToolCall(f"call-{self._counter}", fc["name"], dict(fc.get("args", {}))))
            elif "text" in part:
                texts.append(part["text"])
        return Reply(text="".join(texts) or None, tool_calls=calls, tokens=tokens)
