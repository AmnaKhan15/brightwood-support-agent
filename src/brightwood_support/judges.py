"""LLM-as-judge evaluators for answer quality, built on openevals.

Safety is never judged by a model: whether money moved, whether another customer's data leaked or
whether the right tool ran is checked in code (see evals/run_conversation_eval.py). A judge model
grades what code cannot: is the answer grounded in the help articles it was given, and does it say
the same thing as a reference answer.

A judge is only trusted after calibration: `evals/run_conversation_eval.py --calibrate` scores
hand-labelled examples (evals/judge_calibration.json) and reports how often the judge agrees.
"""
from __future__ import annotations

import os


def judge_model(env=os.environ):
    """The judge: a strong Gemini model, deterministic. A different (stronger) model than the one being graded."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    model = env.get("JUDGE_MODEL") or env.get("GEMINI_STRONG_MODEL") or env.get("GEMINI_MODEL")
    if not (env.get("GEMINI_API_KEY") and model):
        raise RuntimeError("the judge needs GEMINI_API_KEY and JUDGE_MODEL (or GEMINI_STRONG_MODEL)")
    return ChatGoogleGenerativeAI(model=model, google_api_key=env["GEMINI_API_KEY"], temperature=0, max_retries=2, timeout=60)


def build_judges(chat_model) -> dict:
    from openevals.llm import create_llm_as_judge
    from openevals.prompts import CORRECTNESS_PROMPT, RAG_GROUNDEDNESS_PROMPT

    return {
        "groundedness": create_llm_as_judge(prompt=RAG_GROUNDEDNESS_PROMPT, judge=chat_model, feedback_key="groundedness"),
        "correctness": create_llm_as_judge(prompt=CORRECTNESS_PROMPT, judge=chat_model, feedback_key="correctness"),
    }


def grade(judges: dict, question: str, answer: str, context: str, reference: str | None) -> dict:
    """Run the judges that apply. Returns {name: {"score": bool, "comment": str}}."""
    out = {}
    if context.strip():
        r = judges["groundedness"](outputs=answer, context=context)
        out["groundedness"] = {"score": bool(r["score"]), "comment": r.get("comment", "")}
    if reference:
        r = judges["correctness"](inputs=question, outputs=answer, reference_outputs=reference)
        out["correctness"] = {"score": bool(r["score"]), "comment": r.get("comment", "")}
    return out
