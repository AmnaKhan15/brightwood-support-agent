"use client";

import { useHealth } from "@/components/providers";
import { Card, Eyebrow, Pill } from "@/components/ui";

const STEPS = [
  ["Sandbox and sign-in", "Every visitor gets a private copy of the store database (a Postgres schema). The customer id comes from the session, never from the AI.", "service.py, db.py"],
  ["Mask private data", "Card numbers, passwords and other people's emails are hidden before any AI reads them, and again on the way out.", "guardrails.py"],
  ["The supervisor routes", "A LangGraph supervisor hands the message to a policy, orders or billing specialist. A model decides when one is configured; clear keyword rules take over if it fails.", "agent.py"],
  ["Least privilege per agent", "Each specialist only gets the tools its job needs. The policy agent cannot see orders or move money, even if it is fooled.", "agent.py, tools.py"],
  ["Search the help articles", "Hybrid search over pgvector: a word vector and a meaning vector (Gemini embeddings) per passage. The best passages become the AI's context.", "rag/"],
  ["The gateway picks a model", "Routes to a fast or strong Gemini model, reuses cached answers, falls back to the offline assistant, and stops calling a provider that keeps failing.", "gateway.py, providers.py"],
  ["Tools with rules", "Every tool call is validated, checked against the store's rules, and run with a timeout and a retry. Unknown tools and bad arguments are rejected.", "agent.py, shop.py"],
  ["Approval as a workflow", "Refunds over $50 (or $100 in one chat) pause in a LangGraph interrupt, saved in Postgres. A manager's signed decision resumes it as a background job.", "workflows.py, jobs.py"],
  ["Record and measure", "Messages, runs, an audit log and a global run log for metrics. Every step is a trace span, exported to Grafana over OpenTelemetry.", "runlog.py, telemetry.py"],
];

const CONCEPTS = [
  ["Multi-agent (LangGraph)", "A supervisor graph and specialist agents with their own prompts and tools, instead of one agent that can do everything.", "agent.py"],
  ["Human in the loop", "A durable interrupt: the refund waits, across restarts, until a person with the right role decides.", "workflows.py"],
  ["RAG with pgvector", "Look up the right help text first and give it to the AI, instead of trusting what it learned in training.", "rag/store.py"],
  ["Rules below the model", "Cancel, return and refund rules live in the data layer, so a fooled model still cannot break them.", "shop.py"],
  ["Prompt injection defence", "Customer text is data. Attempts are flagged and logged; the rules do not depend on the model behaving.", "guardrails.py"],
  ["LLM gateway", "One front door for several models: routing, cache, fallback, circuit breaker, per-provider stats.", "gateway.py"],
  ["Cost control", "Token budget per run, step cap, a daily cap on real-model calls shared through Redis, and a cache.", "service.py, state.py"],
  ["Background jobs", "Refunds and webhooks run on a Redis queue (Dramatiq) with retries; idempotency keys make retries safe.", "jobs.py"],
  ["Evals in CI", "Safety scenarios, end-to-end conversations with code checks, and a retrieval gate. LLM-as-judge and LangSmith for quality.", "evals/"],
  ["Fine-tuning", "Filtered teacher trajectories become training data for a smaller model, adopted only if it matches the evals and costs less.", "finetune/"],
  ["Observability", "JSON logs with request ids, OpenTelemetry traces and metrics, LangSmith traces of every agent step.", "telemetry.py"],
  ["MCP server", "The same tools, with the same safety rules, offered to any MCP client.", "mcp_server.py"],
];

export default function HowItWorks() {
  const { data: h } = useHealth();
  return (
    <div className="flex flex-col gap-10">
      <section className="flex flex-col gap-5">
        <div>
          <Eyebrow>How it works</Eyebrow>
          <h1 className="mt-1 text-3xl font-bold">The journey of one message</h1>
          <p className="mt-2 max-w-3xl text-muted">Open the chat, send a message, then press <b>Behind the scenes</b>. You will see each of these steps for your own message, with the real rows, scores, prompts and timings.</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {STEPS.map(([title, text, code], n) => (
            <Card key={title} className="flex flex-col gap-2">
              <span className="font-mono text-xs font-bold text-brand">STEP {n + 1}</span>
              <h2 className="font-semibold">{title}</h2>
              <p className="text-sm text-muted">{text}</p>
              <code className="mt-auto font-mono text-xs text-muted">{code}</code>
            </Card>
          ))}
        </div>
      </section>
      <section className="flex flex-col gap-4">
        <h2 className="text-2xl font-bold">Concepts in plain words</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {CONCEPTS.map(([title, text, code]) => (
            <div key={title} className="flex flex-col gap-1.5 rounded-2xl border border-line p-4">
              <h3 className="font-semibold">{title}</h3>
              <p className="text-sm text-muted">{text}</p>
              <code className="font-mono text-xs text-muted">{code}</code>
            </div>
          ))}
        </div>
      </section>
      <Card className="flex flex-col gap-3">
        <h2 className="text-lg font-bold">What is running right now</h2>
        {h ? (
          <>
            <div className="flex flex-wrap gap-1.5">
              <Pill tone="brand">{h.mode}</Pill>
              <Pill>{h.agents}</Pill>
              <Pill>database: {h.database}</Pill>
              <Pill>search: {h.retrieval}</Pill>
              <Pill>jobs: {h.jobs}</Pill>
              <Pill>version {h.version}</Pill>
            </div>
            <ul className="list-disc pl-5 text-sm text-muted">
              <li>{h.mode.includes("gemini") ? "Gemini answers when it can. If it is slow, down, or the daily cap is used, the offline assistant answers and the chat says so." : "No AI key is set, so a backup assistant made of simple rules (not an AI model) answers. It goes through the same agents, tools and safety checks. Add a Gemini key to switch on the real AI."}</li>
              <li>Customers, orders and products are invented. Each visitor&apos;s data is deleted after 30 minutes idle.</li>
              <li>Staff sign-in here is {h.staff_login === "demo" ? "in demo mode so visitors can try both roles; a real deployment uses an access code or an identity provider (Okta, Auth0, Cognito)" : h.staff_login === "access-code" ? "protected by an access code" : "turned off"}.</li>
            </ul>
          </>
        ) : <p className="text-sm text-muted">Loading…</p>}
      </Card>
    </div>
  );
}
