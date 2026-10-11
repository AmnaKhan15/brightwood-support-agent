"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useApp, useAppState, useHealth } from "@/components/providers";
import { Button, Card, Eyebrow, GatewayTable, Note, Pill, Stat, Table } from "@/components/ui";
import { cents, pct, usd } from "@/lib/api";
import type { Metrics } from "@/lib/types";

function fmt(metric: string, v: number | null) {
  if (v == null) return "–";
  if (metric.endsWith("_rate")) return pct(v);
  if (metric.endsWith("_usd")) return usd(v, 4);
  if (metric.endsWith("_ms")) return `${Math.round(v)} ms`;
  if (metric.endsWith("_s")) return v < 120 ? `${Math.round(v)} s` : `${Math.round(v / 60)} min`;
  return String(v);
}

function SignIn() {
  const { api, setStaff, staff } = useApp();
  const { data: health } = useHealth();
  const [code, setCode] = useState("");
  const [role, setRole] = useState("support_manager");
  const [error, setError] = useState<string | null>(null);

  async function login(asRole: string, accessCode?: string) {
    setError(null);
    try {
      const r = await api<{ token: string }>("/api/staff/login", {
        method: "POST",
        body: { role: asRole, name: asRole === "agent" ? "ai-assistant" : "support.manager", code: accessCode },
      });
      setStaff({ token: r.token, role: asRole });
      setCode("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (staff) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Pill tone="ok">signed in as {staff.role}</Pill>
        <Button size="sm" variant="ghost" onClick={() => setStaff(null)}>Sign out</Button>
      </div>
    );
  }
  const mode = health?.staff_login;
  return (
    <div className="flex flex-col gap-3">
      {mode === "demo" && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="solid" onClick={() => login("support_manager")}>Sign in as support manager</Button>
          <Button size="sm" variant="ghost" onClick={() => login("agent")} title="A test: this account belongs to the AI assistant and must be refused">
            Test: sign in as the AI assistant
          </Button>
        </div>
      )}
      {mode === "access-code" && (
        <form
          className="flex flex-wrap gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            void login(role, code);
          }}
        >
          <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role" className="rounded-xl border border-line bg-surface px-2 py-2 text-sm">
            <option value="support_manager">support manager</option>
            <option value="agent">agent (test)</option>
          </select>
          <input type="password" value={code} onChange={(e) => setCode(e.target.value)} placeholder="Staff access code" aria-label="Staff access code"
            autoComplete="current-password" className="min-w-0 flex-1 rounded-xl border border-line bg-bg px-3 py-2 text-sm" />
          <Button type="submit" size="sm" variant="solid" disabled={!code}>Sign in</Button>
        </form>
      )}
      {mode === "off" && <Note>Staff sign-in is turned off on this server.</Note>}
      {error && <Note tone="bad">{error}</Note>}
    </div>
  );
}

export default function Staff() {
  const { api, staff } = useApp();
  const qc = useQueryClient();
  const [note, setNote] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const { data, error } = useAppState({ poll: (d) => (d?.approvals.some((a) => a.status === "processing") ? 1500 : false) });
  const { data: health } = useHealth();
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api<Metrics>("/api/metrics?days=7"), refetchInterval: 15_000 });

  async function decide(id: number, decision: "approve" | "reject") {
    setNote(null);
    try {
      const r = await api<{ id: number; status: string; by: string; role: string }>(`/api/approvals/${id}`, {
        method: "POST", token: staff?.token, body: { decision },
      });
      setNote({ tone: "ok", text: r.status === "processing" ? `Approval #${r.id} is being processed in the background.` : `Approval #${r.id} ${r.status} by ${r.by} (${r.role}).` });
    } catch (e) {
      setNote({ tone: "bad", text: (e as Error).message });
    }
    await Promise.all([qc.invalidateQueries({ queryKey: ["state"] }), qc.invalidateQueries({ queryKey: ["metrics"] })]);
  }

  if (error) return <Note tone="bad">{(error as Error).message}</Note>;
  if (!data) return <p className="text-muted">Loading…</p>;
  const m = metrics.data;

  return (
    <section className="flex flex-col gap-6">
      <div>
        <Eyebrow>Staff only</Eyebrow>
        <h1 className="mt-1 text-3xl font-bold">Support operations</h1>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.1fr_1fr]">
        <div className="flex min-w-0 flex-col gap-5">
          <Card className="flex flex-col gap-4">
            <h2 className="text-lg font-bold">Refunds waiting for a person</h2>
            <SignIn />
            <p className="text-sm text-muted">
              Sign-in gives you a signed token (RS256). Each decision is checked against the role inside it, so the assistant&apos;s own account can never
              approve what it asked for. An approval resumes a paused LangGraph workflow, and the refund runs as a background job.
            </p>
            {note && <Note tone={note.tone}>{note.text}</Note>}
            <div className="flex flex-col gap-2.5">
              {data.approvals.length ? [...data.approvals].reverse().map((a) => (
                <div key={a.id} className="flex flex-col gap-2 rounded-xl border border-line p-3">
                  <div className="flex items-center justify-between gap-2">
                    <b>Refund {usd(a.amount)} · <span className="font-mono">{a.order_id}</span></b>
                    <Pill tone={a.status === "approved" ? "ok" : a.status === "rejected" ? "no" : "wait"}>{a.status}</Pill>
                  </div>
                  <div className="text-sm text-muted">{a.customer} · needs {a.needs}{a.decided_by ? ` · decided by ${a.decided_by}` : ""}<br />{a.reason}</div>
                  {a.status === "pending" && (
                    <div className="flex gap-2">
                      <Button size="sm" variant="solid" disabled={!staff} onClick={() => decide(a.id, "approve")}>Approve</Button>
                      <Button size="sm" variant="danger" disabled={!staff} onClick={() => decide(a.id, "reject")}>Reject</Button>
                    </div>
                  )}
                </div>
              )) : (
                <p className="text-sm text-muted">Nothing is waiting. Press Customer at the top, choose Priya Nair, and ask support to &ldquo;Refund order O2001&rdquo;. It is over the assistant&apos;s $50 limit, so it lands here.</p>
              )}
            </div>
          </Card>

          <Card className="flex flex-col gap-3">
            <Eyebrow>Audit log</Eyebrow>
            <h2 className="text-lg font-bold">Who decided what</h2>
            <Table head={["when", "who", "role", "action", "detail"]} rows={data.audit.map((a) => [String(a.created_at).slice(11), a.actor, a.role, a.action, a.detail])} />
          </Card>
        </div>

        <div className="flex min-w-0 flex-col gap-5">
          <Card className="flex flex-col gap-3">
            <Eyebrow>Business outcomes · last {m?.window_days ?? 7} days, all visitors</Eyebrow>
            <h2 className="text-lg font-bold">Is the assistant doing its job?</h2>
            {m ? (
              <>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  <Stat value={m.conversations} label="conversations" />
                  <Stat value={pct(m.containment_rate)} label="resolved without a person" />
                  <Stat value={pct(m.escalation_rate)} label="handed to a person" />
                  <Stat value={pct(m.approval_rate)} label="sent for approval" />
                  <Stat value={m.rule_blocks} label="tool calls blocked by rules" />
                  <Stat value={m.injection_flags} label="injection attempts flagged" />
                </div>
                <Table
                  head={["success target", "goal", "now", ""]}
                  rows={m.targets.map((t) => [t.meaning, t.target.replace(/_/g, " "), fmt(t.metric, t.value),
                    t.met == null ? <Pill key={t.metric}>no data</Pill> : t.met ? <Pill key={t.metric} tone="ok">met</Pill> : <Pill key={t.metric} tone="no">missed</Pill>])}
                />
                <p className="text-xs text-muted">By agent: {Object.entries(m.by_agent).map(([a, n]) => `${a} ${n}`).join(" · ") || "none yet"}</p>
              </>
            ) : <p className="text-sm text-muted">Loading…</p>}
          </Card>

          <Card className="flex flex-col gap-3">
            <Eyebrow>System health · version {health?.version}</Eyebrow>
            <h2 className="text-lg font-bold">{health?.mode}</h2>
            {health && (
              <>
                <div className="flex flex-wrap gap-1.5">
                  <Pill tone="brand">{health.agents}</Pill>
                  <Pill>db: {health.database}</Pill>
                  <Pill tone={health.redis ? "ok" : "no"}>redis {health.redis ? "up" : "down"}</Pill>
                  <Pill>jobs: {health.jobs}</Pill>
                  <Pill>search: {health.retrieval}</Pill>
                  <Pill>payments: {health.payments}</Pill>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Stat value={`${health.ai_calls_today}/${health.ai_daily_cap}`} label="real-model calls today" />
                  <Stat value={health.sessions} label="live sandboxes" />
                </div>
                <GatewayTable providers={health.gateway.providers} />
              </>
            )}
          </Card>

          <Card className="flex flex-col gap-3">
            <Eyebrow>Handed to a person</Eyebrow>
            <Table head={["id", "order", "summary"]} rows={data.tickets.map((t) => [t.id, t.order_id, t.summary])} />
          </Card>
          <Card className="flex flex-col gap-3">
            <Eyebrow>Money out · {health?.payments}</Eyebrow>
            <Table head={["id", "order", "amount", "by", "provider id", "status"]}
              rows={data.refunds.map((r) => [r.id, r.order_id, cents(r.amount_cents ?? 0), r.via, r.provider_refund_id, r.status])} />
          </Card>
          <Card className="flex flex-col gap-3">
            <Eyebrow>Every AI run in this sandbox</Eyebrow>
            <Table head={["id", "agent", "ended", "steps", "tokens", "tools", "answered by", "ms"]}
              rows={data.runs.map((r) => [r.id, r.agent, r.stopped, r.steps, r.tokens, r.tools || "none", `${r.provider ?? ""}${r.route ? ` / ${r.route}` : ""}`, r.millis])} />
          </Card>
        </div>
      </div>
    </section>
  );
}
