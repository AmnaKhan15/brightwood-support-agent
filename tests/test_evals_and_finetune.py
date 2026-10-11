import importlib.util
import unittest
from pathlib import Path

from brightwood_support.agent import KeywordRouter, Reply, ScriptedModel, ToolCall, run_agent
from brightwood_support.approvals import ApprovalQueue
from brightwood_support.conversation_eval import check, load_cases, run_case
from brightwood_support.finetune import keep, overlaps, synthetic_prompts, to_openai, to_vertex
from brightwood_support.judges import grade
from brightwood_support.playbook import PlaybookModel
from brightwood_support.rag import HashingEmbedder, InMemoryStore, load_corpus
from brightwood_support.service import HELP_DIR, Service
from brightwood_support.shop import Shop
from brightwood_support.tools import build_toolbox

ROOT = Path(__file__).resolve().parent.parent


def _load(path: str):
    spec = importlib.util.spec_from_file_location(Path(path).stem, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def offline_run(text: str, customer: str = "C1"):
    store = InMemoryStore(HashingEmbedder())
    store.add(load_corpus(HELP_DIR))
    shop = Shop()
    tb = build_toolbox(store, shop, customer)
    return run_agent(PlaybookModel(), tb, ApprovalQueue(tb.executors()), text, router=KeywordRouter()), tb


class ConversationEvalTests(unittest.TestCase):
    def test_cases_are_well_formed(self):
        cases = load_cases()
        self.assertGreaterEqual(len(cases), 20)
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        for c in cases:
            self.assertIn(c["customer"], ("C1", "C2", "C3"))
            self.assertTrue(c["turns"] and c.get("reference"))

    def test_offline_assistant_passes_the_code_checks(self):
        svc = Service(env={"DEMO_STAFF_LOGIN": "true"}, per_minute=1000)
        by_id = {c["id"]: c for c in load_cases()}
        for cid in ("billing-large-refund-waits", "guard-card-number", "orders-memory", "policy-shipping-cost"):
            out = run_case(svc, by_id[cid])
            self.assertEqual(check(by_id[cid], out), [], cid)

    def test_checks_catch_money_and_leaks(self):
        case = {"expect": {"no_money": True, "reply_none": ["4111 1111 1111 1111"], "cite": True}}
        out = {"reply": "Your card 4111 1111 1111 1111 is fine", "tools": [], "refunds": [{"amount_cents": 500}], "messages": [], "agent": None, "state": "ok"}
        fails = check(case, out)
        self.assertEqual(len(fails), 3)

    def test_grade_uses_the_judges_that_apply(self):
        calls = []
        judges = {"groundedness": lambda **kw: calls.append("g") or {"score": True, "comment": "ok"},
                  "correctness": lambda **kw: calls.append("c") or {"score": False, "comment": "differs"}}
        out = grade(judges, "q", "a", "ctx", "ref")
        self.assertEqual((out["groundedness"]["score"], out["correctness"]["score"], calls), (True, False, ["g", "c"]))
        self.assertEqual(grade(judges, "q", "a", "", None), {})


class FinetuneTests(unittest.TestCase):
    def test_eval_cases_are_held_out(self):
        held = [t for c in load_cases() for t in c["turns"]]
        prompts, excluded = synthetic_prompts(held)
        self.assertGreater(len(prompts), 50)
        self.assertGreater(excluded, 0)
        for p in prompts:
            self.assertFalse(overlaps(p["turns"][0], held), p)

    def test_vertex_and_openai_formats(self):
        result, tb = offline_run("Where is order O1003?")
        specs = tb.restricted(("get_order", "list_orders")).specs()
        v = to_vertex(result.messages, result.final_text, specs)
        self.assertEqual(v["contents"][0]["role"], "user")
        self.assertEqual(v["contents"][-1], {"role": "model", "parts": [{"text": result.final_text}]})
        call = next(p for c in v["contents"] for p in c["parts"] if "functionCall" in p)
        answer = next(p for c in v["contents"] for p in c["parts"] if "functionResponse" in p)
        self.assertEqual(call["functionCall"]["name"], answer["functionResponse"]["name"])
        o = to_openai(result.messages, result.final_text, specs)
        ids = [tc["id"] for m in o["messages"] if m.get("tool_calls") for tc in m["tool_calls"]]
        self.assertEqual(ids, [m["tool_call_id"] for m in o["messages"] if m["role"] == "tool"])
        self.assertEqual(o["messages"][-1]["role"], "assistant")

    def test_filters(self):
        prompt = {"expect": {"tools_include": ["get_order"]}}
        good, _ = offline_run("Where is order O1003?")
        self.assertIsNone(keep(prompt, good))
        self.assertIn("did not call", keep({"expect": {"tools_include": ["request_refund"]}}, good))
        store = InMemoryStore(HashingEmbedder())
        shop = Shop()
        tb = build_toolbox(store, shop, "C1")
        bad = run_agent(ScriptedModel([Reply(tool_calls=[ToolCall("c", "delete_order", {})]), Reply(text="done")]), tb, ApprovalQueue(tb.executors()), "x")
        self.assertEqual(keep({"expect": {}}, bad), "made an invalid tool call")
        leaky = run_agent(ScriptedModel([Reply(text="your card 4111 1111 1111 1111")]), tb, ApprovalQueue(tb.executors()), "x")
        self.assertEqual(keep({"expect": {}}, leaky), "contains private data")

    def test_compare_decision_rule(self):
        decide = _load("finetune/compare.py").decide
        base = {"pass_rate": 0.95, "p95_ms": 3000, "cost_per_conversation_usd": 0.004, "groundedness_rate": 0.9}
        self.assertEqual(decide(base, {**base, "cost_per_conversation_usd": 0.001}), [])
        self.assertIn("lower code-check pass rate", decide(base, {**base, "pass_rate": 0.9, "cost_per_conversation_usd": 0.001}))
        self.assertIn("groundedness_rate dropped", decide(base, {**base, "groundedness_rate": 0.8, "cost_per_conversation_usd": 0.001}))
        self.assertIn("neither cheaper nor faster", decide(base, dict(base)))


if __name__ == "__main__":
    unittest.main()
