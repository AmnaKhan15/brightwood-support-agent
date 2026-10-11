"""Real model providers, through LangChain.

`LangChainModel` adapts any LangChain chat model that supports tool calling (Gemini here; Claude or
OpenAI work the same way) to the small `Model` protocol the agent and the gateway use. That keeps
the gateway's routing, cache, fallback and circuit breaker in front of every provider, and keeps the
offline assistant as a drop-in fallback.

The model id and API key come from the environment, never code.
"""
from __future__ import annotations

import os

from .agent import Reply, ToolCall


def tool_schema(spec: dict) -> dict:
    """Our tool spec as an OpenAI-style function definition, which every LangChain chat model accepts."""
    types = spec.get("types", {})
    return {
        "type": "function",
        "function": {
            "name": spec["name"],
            "description": spec["description"],
            "parameters": {
                "type": "object",
                "properties": {p: {"type": types.get(p, "string")} for p in spec["params"]},
                "required": list(spec["params"]),
            },
        },
    }


def to_langchain(messages: list[dict]) -> list:
    """Our messages (system, user, assistant with tool calls, tool results) as LangChain messages."""
    from langchain_core.messages import (
        AIMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )

    out, names = [], {}
    for m in messages:
        role = m["role"]
        if role == "system":
            out.append(SystemMessage(m["content"]))
        elif role == "user":
            out.append(HumanMessage(m["content"]))
        elif role == "assistant":
            calls = []
            for c in m.get("tool_calls", []):
                names[c.id] = c.name
                calls.append({"name": c.name, "args": c.args, "id": c.id, "type": "tool_call"})
            out.append(AIMessage(content=m.get("content") or "", tool_calls=calls))
        elif role == "tool":
            out.append(ToolMessage(m["content"], tool_call_id=m["tool_call_id"], name=names.get(m["tool_call_id"], "tool")))
    return out


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content or [])


class LangChainModel:
    def __init__(self, chat_model, name: str) -> None:
        self._chat = chat_model
        self.name = name
        self._counter = 0

    def next(self, messages: list[dict], tool_specs: list[dict]) -> Reply:
        model = self._chat.bind_tools([tool_schema(s) for s in tool_specs]) if tool_specs else self._chat
        ai = model.invoke(to_langchain(messages))
        calls = []
        for tc in getattr(ai, "tool_calls", None) or []:
            self._counter += 1
            calls.append(ToolCall(tc.get("id") or f"call-{self._counter}", tc["name"], dict(tc.get("args") or {})))
        usage = getattr(ai, "usage_metadata", None) or {}
        return Reply(text=_text(ai.content) or None, tool_calls=calls, tokens=int(usage.get("total_tokens", 0)))


def GeminiModel(model: str | None = None, api_key: str | None = None, timeout: float = 20.0, env=os.environ) -> LangChainModel:  # noqa: N802
    """Gemini via langchain-google-genai. Retries are left to the gateway, which falls back instead of waiting.

    With GEMINI_USE_VERTEX=true the model is called on Vertex AI instead of the Gemini API (Google Cloud
    credentials, GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION). That is how a fine-tuned model is served:
    set GEMINI_MODEL to the tuned model's endpoint.
    """
    from langchain_google_genai import ChatGoogleGenerativeAI

    model = model or env.get("GEMINI_MODEL", "")
    if env.get("GEMINI_USE_VERTEX", "").lower() in ("1", "true", "yes"):
        if not model:
            raise ValueError("GEMINI_MODEL must be set")
        chat = ChatGoogleGenerativeAI(model=model, vertexai=True, project=env.get("GOOGLE_CLOUD_PROJECT"),
                                      location=env.get("GOOGLE_CLOUD_LOCATION", "us-central1"), temperature=0, max_retries=1, timeout=timeout)
        return LangChainModel(chat, f"vertex:{model}")
    api_key = api_key or env.get("GEMINI_API_KEY", "")
    if not model or not api_key:
        raise ValueError("GEMINI_MODEL and GEMINI_API_KEY must be set")
    chat = ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0, max_retries=1, timeout=timeout)
    return LangChainModel(chat, f"gemini:{model}")
