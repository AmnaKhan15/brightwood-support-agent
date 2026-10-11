"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { Row } from "@/lib/types";
import { useApp } from "./providers";
import { Button, Note, ScoreBar, Stat, Table, cx } from "./ui";

const TABS = [
  ["flow", "This question"],
  ["prompt", "What the AI read"],
  ["db", "Database"],
  ["trace", "Trace and gateway"],
] as const;
type Tab = (typeof TABS)[number][0];
const TABLES = ["messages", "runs", "approvals", "orders", "tickets", "refunds", "audit"];

function Code({ children }: { children: string }) {
  return <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-surface-2 p-3 font-mono text-xs [overflow-wrap:anywhere]">{children}</pre>;
}

function Database() {
  const { api, sid } = useApp();
  const [table, setTable] = useState("messages");
  const { data = [], isLoading } = useQuery({ queryKey: ["table", sid, table], queryFn: () => api<Row[]>(`/api/table/${table}`) });
  const cols = data[0] ? Object.keys(data[0]) : [];
  return (
    <div className="flex flex-col gap-3">
      <Note>This is your private sandbox database, live. Each visitor has their own, deleted after 30 minutes idle.</Note>
      <div className="flex flex-wrap gap-1.5">
        {TABLES.map((t) => (
          <Button key={t} size="sm" variant={t === table ? "solid" : "outline"} onClick={() => setTable(t)}>{t}</Button>
        ))}
      </div>
      {isLoading ? <p className="text-sm text-muted">Loading…</p> : <Table head={cols} rows={data.map((r) => cols.map((c) => r[c]))} />}
    </div>
  );
}

export function Inspector() {
  const { drawerOpen, setDrawerOpen, inspect: i } = useApp();
  const [tab, setTab] = useState<Tab>("flow");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawerOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setDrawerOpen]);

  if (!drawerOpen) return null;
  const empty = <Note>Send a message in the chat first. This panel then shows what happened to it.</Note>;
  const maxSpan = i ? Math.max(...i.tools.map((t) => t.duration_s), 1e-6) : 1;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={() => setDrawerOpen(false)} aria-hidden />
      <aside aria-label="Behind the scenes" className="fixed inset-y-0 right-0 z-50 flex w-full max-w-2xl flex-col border-l border-line bg-bg shadow-card">
        <header className="flex items-start gap-3 border-b border-line px-5 py-4">
          <div className="flex-1">
            <div className="text-xs font-bold uppercase tracking-[0.14em] text-brand">Behind the scenes</div>
            <h2 className="text-xl font-bold">What happened to your message</h2>
          </div>
          <Button size="sm" variant="ghost" aria-label="Close" onClick={() => setDrawerOpen(false)}>✕</Button>
        </header>
        <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-line px-4 py-2">
          {TABS.map(([k, label]) => (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={tab === k}
              onClick={() => setTab(k)}
              className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-semibold", tab === k ? "bg-brand-soft text-brand" : "text-muted hover:text-ink")}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {tab === "db" ? (
            <Database />
          ) : !i ? (
            empty
          ) : tab === "flow" ? (
            <ol className="flex flex-col gap-4">
              {[
                ...i.steps.filter((s) => s.title.startsWith("The supervisor")).map((s) => ({ kind: s.kind, title: s.title, body: <><p className="text-sm text-muted">{s.detail}</p>{s.data && <Code>{s.data}</Code>}</> })),
                {
                  kind: "", title: "You typed",
                  body: <>
                    <Code>{i.typed}</Code>
                    <p className="mt-2 text-sm text-muted">{i.typed !== i.masked ? "Private details were hidden. The AI only sees:" : "Nothing private was found, so the AI sees the same text."}</p>
                    {i.typed !== i.masked && <Code>{i.masked}</Code>}
                  </>,
                },
                {
                  kind: "", title: "Stored in the database",
                  body: <>
                    <p className="text-sm text-muted">The masked text and the answer are saved as rows, plus one row describing this AI run.</p>
                    <Code>{i.stored.map((s) => `${s.table} row ${s.id}${s.role ? ` (${s.role})` : ""}`).join("\n")}</Code>
                  </>,
                },
                ...(i.retrieved.length
                  ? [{
                      kind: "", title: `Found in the help articles (${i.retrieval} search)`,
                      body: <div className="flex flex-col gap-2">
                        <p className="text-sm text-muted">These passages were handed to the AI as its context. A higher score means a closer match.</p>
                        {i.retrieved.map((r) => (
                          <div key={r.id} className="rounded-lg border border-line p-3">
                            <div className="mb-1 flex justify-between font-mono text-xs"><span className="text-brand">{r.id}</span><span>{r.score.toFixed(2)}</span></div>
                            <ScoreBar score={r.score} />
                            <p className="mt-2 text-sm">{r.text}</p>
                          </div>
                        ))}
                      </div>,
                    }]
                  : []),
                ...i.steps.filter((s) => !s.title.startsWith("The supervisor")).map((s) => ({ kind: s.kind, title: s.title, body: <><p className="text-sm text-muted">{s.detail}</p>{s.data && <Code>{s.data}</Code>}</> })),
                {
                  kind: "ok", title: "Answer sent",
                  body: <p className="text-sm text-muted">
                    Written by <b className="text-ink">{i.provider ?? "no model"}</b> (route: {i.route ?? "none"}) for the <b className="text-ink">{i.agent ?? "single"}</b> agent.
                    Took {i.millis} ms and {i.tokens} tokens across {i.summary.model_calls} model call(s) and {i.summary.tool_calls} tool call(s). Ended because: {i.stopped}.
                  </p>,
                },
              ].map((item, n) => (
                <li key={n} className="flex gap-3">
                  <span className={cx("grid size-7 shrink-0 place-items-center rounded-full text-xs font-bold",
                    item.kind === "ok" ? "bg-ok-soft text-ok" : item.kind === "wait" ? "bg-warn-soft text-warn" : item.kind === "no" ? "bg-bad-soft text-bad" : "bg-surface-2 text-muted")}>
                    {n + 1}
                  </span>
                  <div className="min-w-0 flex-1"><h3 className="mb-1 font-semibold">{item.title}</h3>{item.body}</div>
                </li>
              ))}
            </ol>
          ) : tab === "prompt" ? (
            <div className="flex flex-col gap-3">
              <Note>Everything the AI was given for your last question: its specialist&apos;s rules first, then the conversation, then the search results and order data it asked for.</Note>
              {i.prompt.map((m, n) => (
                <div key={n} className="rounded-xl border border-line bg-surface p-3">
                  <div className="mb-1.5 text-xs font-bold uppercase tracking-wide text-muted">{m.role === "tool" ? "tool result" : m.role === "user" ? "customer" : m.role}</div>
                  <Code>{m.text}</Code>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Stat value={i.summary.model_calls} label="model calls" />
                <Stat value={i.summary.tool_calls} label="tool calls" />
                <Stat value={i.tokens} label="tokens" />
                <Stat value={`${i.millis} ms`} label="total time" />
              </div>
              <div className="flex flex-col gap-2">
                <h3 className="font-semibold">Trace</h3>
                <p className="text-sm text-muted">One bar per routing decision, model call and tool call. The same spans go to OpenTelemetry when it is configured.</p>
                {i.tools.map((t, n) => (
                  <div key={n} className="grid grid-cols-[9rem_1fr_4.5rem] items-center gap-2 font-mono text-xs">
                    <span className="truncate">{t.name === "tool_call" ? `tool: ${t.attrs.tool}` : t.name === "route" ? `route: ${t.attrs.agent}` : `model: ${t.attrs.provider ?? ""}`}</span>
                    <div className="h-2 rounded-full bg-surface-2"><i className={cx("block h-2 rounded-full", t.name === "tool_call" ? "bg-warn" : "bg-brand")} style={{ width: `${Math.max(2, (t.duration_s / maxSpan) * 100)}%` }} /></div>
                    <span className="text-right">{(t.duration_s * 1000).toFixed(1)} ms</span>
                  </div>
                ))}
              </div>
              <div className="flex flex-col gap-2">
                <h3 className="font-semibold">Gateway</h3>
                <p className="text-sm text-muted">It tries providers in order, skips one that keeps failing (circuit breaker), reuses repeated answers (cache) and degrades instead of stopping.</p>
                <Table head={["provider", "calls", "failures", "skipped", "avg s"]}
                  rows={Object.entries(i.gateway.providers).map(([n, p]) => [n, p.calls, p.failures, p.skipped_open, p.avg_seconds])} />
                <p className="text-xs text-muted">cache hits: {i.gateway.cache_hits} · fallbacks: {i.gateway.fallbacks} · degraded: {i.gateway.degraded}</p>
              </div>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
