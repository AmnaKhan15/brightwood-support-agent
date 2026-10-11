"""Fine-tuning data: turn good agent runs into supervised training examples.

Why fine-tune here: distillation. A strong model (the teacher) handles the conversations well but
costs more and is slower; a small model (the student) tuned on the teacher's *filtered* trajectories
can take over the routine traffic. It is only adopted if it does at least as well on the held-out
evals and costs less (finetune/compare.py decides).

The pipeline, in order:
  1. Prompts: synthetic customer messages from templates (no real customer data), with any prompt that
     overlaps an eval case removed, so the evals stay a fair test.
  2. Trajectories: each prompt runs through the real agent with the teacher model, so examples include
     the specialist's system prompt, its tool calls, the tool results and the final answer.
  3. Filters: keep a run only if it finished normally, made no invalid tool calls, its outcome matches
     the prompt's intent, and nothing private (card numbers, secrets) appears in it.
  4. Export: JSONL for Vertex AI Gemini supervised tuning, and the OpenAI chat format, split train/val.
"""
from __future__ import annotations

import json
import random
import re

from .guardrails import mask_private
from .rag.embeddings import tokens

# --- 1. prompts -----------------------------------------------------------------------

ORDERS = {
    "C1": {"delivered": ["O1001"], "processing": ["O1002"], "shipped": ["O1003"]},
    "C2": {"delivered": ["O2001", "O2002", "O2003"]},
    "C3": {"shipped": ["O3001"], "processing": ["O3002"]},
}
TEMPLATES = {
    "track": (["Where is {o}?", "Any update on order {o}?", "Can you check the status of {o}", "has {o} shipped yet", "tracking for {o} please"],
              ("shipped", "processing", "delivered"), {"tools_include": ["get_order"]}),
    "cancel": (["Please cancel {o}", "I changed my mind, cancel order {o}", "can I still cancel {o}?", "Stop order {o} before it ships"],
               ("processing", "shipped"), {"tools_include": ["get_order"]}),
    "refund": (["I want a refund for {o}", "Can I get my money back for {o}?", "refund {o} please", "Please refund order {o}, it wasn't what I expected"],
               ("delivered",), {"tools_include": ["request_refund"]}),
    "label": (["I need a return label for {o}", "How do I send back {o}? Please send a label", "return label for order {o}"],
              ("delivered",), {"tools_include": ["get_order"]}),
    "policy": (["What is your returns policy?", "How long do refunds take to arrive?", "Do you charge for shipping?",
                "Can I change my delivery address after ordering?", "How do gift cards work?", "Is my card information stored?",
                "What happens if an item is damaged in transit?", "How long is the warranty on furniture?", "Can I return something I bought on sale?",
                "Do discount codes stack?"], (), {"tools_include": ["search_help"]}),
    "person": (["I'd like to speak to someone", "Can a human help me with this?", "Please get me a real person"], (), {"tools_include": ["escalate_to_human"]}),
}


def overlaps(text: str, held_out: list[str], threshold: float = 0.6) -> bool:
    """True if `text` is close to any held-out eval message (word Jaccard), so it must not be trained on."""
    a = set(tokens(text))
    for other in held_out:
        b = set(tokens(other))
        if a and b and len(a & b) / len(a | b) >= threshold:
            return True
    return False


def synthetic_prompts(held_out: list[str], seed: int = 7) -> tuple[list[dict], int]:
    """All template x customer x order combinations, minus overlaps with the evals. Returns (prompts, excluded)."""
    rows, excluded = [], 0
    for intent, (phrases, statuses, expect) in TEMPLATES.items():
        for cid, orders in ORDERS.items():
            ids = [o for st in statuses for o in orders.get(st, [])] if statuses else [None]
            for oid in ids:
                for phrase in phrases:
                    text = phrase.format(o=oid) if oid else phrase
                    if overlaps(text, held_out):
                        excluded += 1
                        continue
                    rows.append({"customer": cid, "turns": [text], "intent": intent, "expect": expect})
    unique = {(r["customer"], r["turns"][0]): r for r in rows}
    out = list(unique.values())
    random.Random(seed).shuffle(out)
    return out, excluded


# --- 3. filters -----------------------------------------------------------------------

_SECRET = re.compile(r"\b(?:\d[ -]?){13,16}\b|(?i:password|api[_-]?key)\s*[=:]\s*\S+")


def keep(prompt: dict, result) -> str | None:
    """None to keep the trajectory, or the reason it is dropped."""
    if result.stopped != "final" or not (result.final_text or "").strip():
        return f"did not finish ({result.stopped})"
    if any(t["status"] == "rejected" for t in result.tool_log):
        return "made an invalid tool call"
    called = {t["tool"] for t in result.tool_log}
    missing = [t for t in prompt["expect"].get("tools_include", []) if t not in called]
    if missing:
        return f"did not call {missing}"
    blob = json.dumps([m.get("content") for m in result.messages], default=str) + (result.final_text or "")
    if _SECRET.search(blob) or mask_private(result.final_text or "") != (result.final_text or ""):
        return "contains private data"
    return None


# --- 4. export ------------------------------------------------------------------------

def _declarations(tool_specs: list[dict]) -> list[dict]:
    return [{"name": s["name"], "description": s["description"],
             "parameters": {"type": "OBJECT", "properties": {p: {"type": s["types"].get(p, "string").upper()} for p in s["params"]},
                            "required": list(s["params"])}} for s in tool_specs]


def to_vertex(messages: list[dict], final_text: str, tool_specs: list[dict]) -> dict:
    """One Vertex AI Gemini supervised-tuning example (systemInstruction + contents, with function calls)."""
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    contents, names = [], {}
    for m in messages:
        if m["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            parts = []
            for c in m["tool_calls"]:
                names[c.id] = c.name
                parts.append({"functionCall": {"name": c.name, "args": c.args}})
            contents.append({"role": "model", "parts": parts})
        elif m["role"] == "assistant":
            contents.append({"role": "model", "parts": [{"text": m["content"]}]})
        elif m["role"] == "tool":
            part = {"functionResponse": {"name": names.get(m["tool_call_id"], "tool"), "response": {"result": m["content"]}}}
            if contents and contents[-1]["role"] == "user" and "functionResponse" in contents[-1]["parts"][0]:
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
    contents.append({"role": "model", "parts": [{"text": final_text}]})
    return {"systemInstruction": {"role": "system", "parts": [{"text": system}]}, "contents": contents,
            "tools": [{"functionDeclarations": _declarations(tool_specs)}]}


def to_openai(messages: list[dict], final_text: str, tool_specs: list[dict]) -> dict:
    """The same example in the OpenAI chat fine-tuning format, so the dataset is not tied to one vendor."""
    from .providers import tool_schema

    out = []
    for m in messages:
        if m["role"] in ("system", "user"):
            out.append({"role": m["role"], "content": m["content"]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "tool_calls": [{"id": c.id, "type": "function",
                                                             "function": {"name": c.name, "arguments": json.dumps(c.args)}} for c in m["tool_calls"]]})
        elif m["role"] == "assistant":
            out.append({"role": "assistant", "content": m["content"]})
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
    out.append({"role": "assistant", "content": final_text})
    return {"messages": out, "tools": [tool_schema(s) for s in tool_specs]}


def split(rows: list, val_share: float = 0.15, seed: int = 11) -> tuple[list, list]:
    rows = list(rows)
    random.Random(seed).shuffle(rows)
    n_val = max(1, round(len(rows) * val_share)) if len(rows) > 1 else 0
    return rows[n_val:], rows[:n_val]
