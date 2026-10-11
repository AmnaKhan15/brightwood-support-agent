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
from .config import env_flag


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
        self._bound: dict[tuple[str, ...], object] = {}  # one binding per tool set (a specialist has a fixed set)

    def _with_tools(self, tool_specs: list[dict]):
        if not tool_specs:
            return self._chat
        key = tuple(s["name"] for s in tool_specs)
        if key not in self._bound:
            self._bound[key] = self._chat.bind_tools([tool_schema(s) for s in tool_specs])
        return self._bound[key]

    def next(self, messages: list[dict], tool_specs: list[dict]) -> Reply:
        model = self._with_tools(tool_specs)
        ai = model.invoke(to_langchain(messages))
        calls = []
        for tc in getattr(ai, "tool_calls", None) or []:
            self._counter += 1
            calls.append(ToolCall(tc.get("id") or f"call-{self._counter}", tc["name"], dict(tc.get("args") or {})))
        usage = getattr(ai, "usage_metadata", None) or {}
        return Reply(text=_text(ai.content) or None, tool_calls=calls, tokens=int(usage.get("total_tokens", 0)))


def gemini_chat(model: str, env=os.environ, timeout: float = 20.0, max_retries: int = 1):
    """A LangChain Gemini chat model from the environment: the Gemini API with GEMINI_API_KEY, or Vertex AI
    with GEMINI_USE_VERTEX=true (Google Cloud credentials, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION).
    Vertex is how a fine-tuned model is served: set the model to the tuned endpoint."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    if not model:
        raise ValueError("a Gemini model id is required")
    common = {"model": model, "temperature": 0, "max_retries": max_retries, "timeout": timeout}
    if env_flag(env, "GEMINI_USE_VERTEX"):
        return ChatGoogleGenerativeAI(**common, vertexai=True, project=env.get("GOOGLE_CLOUD_PROJECT"),
                                      location=env.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    if not env.get("GEMINI_API_KEY"):
        raise ValueError("GEMINI_API_KEY must be set")
    return ChatGoogleGenerativeAI(**common, google_api_key=env["GEMINI_API_KEY"])


def gemini_configured(env) -> bool:
    return bool(env.get("GEMINI_MODEL") and (env.get("GEMINI_API_KEY") or env_flag(env, "GEMINI_USE_VERTEX")))


def GeminiModel(model: str, env=os.environ, timeout: float = 20.0) -> LangChainModel:  # noqa: N802
    """Gemini for the agents. Retries are left to the gateway, which falls back instead of waiting."""
    return LangChainModel(gemini_chat(model, env, timeout), f"gemini:{model}")
