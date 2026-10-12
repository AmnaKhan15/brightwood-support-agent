"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useApp, useAppState, useHealth } from "@/components/providers";
import { GatewayTable, Note, Pill, Stat, Table, cx } from "@/components/ui";
import { cents, pct, usd } from "@/lib/api";
import type { Approval, Metrics } from "@/lib/types";

function fmt(metric: string, v: number | null) {
  if (v == null) return "–";
  if (metric.endsWith("_rate")) return pct(v);
  if (metric.endsWith("_usd")) return usd(v, 4);
  if (metric.endsWith("_ms")) return `${Math.round(v)} ms`;
  if (metric.endsWith("_s")) return v < 120 ? `${Math.round(v)} s` : `${Math.round(v / 60)} min`;
  return String(v);
}

// Account names like "support.manager" read as "Support manager".
const person = (who: string) => { const t = who.replace(/[._]/g, " "); return t.charAt(0).toUpperCase() + t.slice(1); };

const initials = (name: string) => name.split(" ").map((p) => p[0]).join("").slice(0, 2);

/** One of the desk's three steps: done, happening now, or still to come. */
function Step({ n, title, text, state }: { n: number; title: string; text: string; state: "done" | "now" | "later" }) {
  return (
    <li className={cx("flex gap-3 rounded-2xl border p-4 transition", state === "now" ? "border-ink bg-surface" : "border-line")}>
      <span className={cx("grid size-8 shrink-0 place-items-center rounded-full text-sm font-bold",
        state === "done" ? "bg-ok text-white" : state === "now" ? "bg-accent text-white" : "bg-surface-2 text-muted")}>
        {state === "done" ? "✓" : n}
      </span>
      <span>
        <b className="block text-sm">{title}</b>
        <span className="text-sm text-muted">{text}</span>
      </span>
    </li>
  );
}

function SignIn() {
  const { api, setStaff, staff } = useApp();
  const { data: health } = useHealth();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function login(role: string, accessCode?: string) {
    setError(null);
    try {
      const r = await api<{ token: string }>("/api/staff/login", {
        method: "POST",
        body: { role, name: role === "agent" ? "ai-assistant" : "support.manager", code: accessCode },
      });
      setStaff({ token: r.token, role });
      setCode("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (staff) {
    const ai = staff.role === "agent";
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-surface px-5 py-4">
        <span className="flex items-center gap-3">
          <span className="grid size-9 place-items-center rounded-full bg-ink text-sm font-bold text-bg">{ai ? "AI" : "SM"}</span>
          <span>
            <b className="block text-sm">{ai ? "Signed in as the AI assistant (safety test)" : "Signed in as Support manager"}</b>
            <span className="text-xs text-muted">{ai ? "Try approving: the store will refuse, because the AI can't approve its own refunds." : "You can approve or reject requests below."}</span>
          </span>
        </span>
        <button type="button" onClick={() => setStaff(null)} className="link-underline text-sm font-semibold text-muted hover:text-ink">Sign out</button>
      </div>
    );
  }

  const mode = health?.staff_login;
  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-ink bg-surface p-5">
      <div>
        <b className="block">Sign in to make decisions</b>
        <span className="text-sm text-muted">Only a person with the manager role can approve money going out.</span>
      </div>
      {mode === "demo" && (
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" onClick={() => login("support_manager")}
            className="rounded-full bg-ink px-5 py-3 text-sm font-semibold text-bg transition hover:bg-accent">
            Sign in as Support manager
          </button>
          <button type="button" onClick={() => login("agent")} className="link-underline text-sm font-semibold text-muted hover:text-ink"
            title="A safety test: this account belongs to the AI assistant, and its approvals are refused">
            or test: sign in as the AI
          </button>
        </div>
      )}
      {mode === "access-code" && (
        <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); void login("support_manager", code); }}>
          <input type="password" value={code} onChange={(e) => setCode(e.target.value)} placeholder="Staff access code" aria-label="Staff access code"
            autoComplete="current-password" className="min-w-0 flex-1 rounded-full border border-line bg-bg px-4 py-2.5 text-sm" />
          <button type="submit" disabled={!code} className="rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-bg disabled:opacity-50">Sign in</button>
        </form>
      )}
      {mode === "off" && <Note>Staff sign-in is turned off on this server.</Note>}
      {error && <Note tone="bad">{error}</Note>}
    </div>
  );
}

function RequestCard({ a, signedIn, onDecide }: { a: Approval; signedIn: boolean; onDecide: (id: number, d: "approve" | "reject") => void }) {
  const pending = a.status === "pending";
  return (
    <article className={cx("flex flex-col gap-4 rounded-3xl border bg-surface p-5 sm:p-6", pending ? "border-ink" : "border-line")}>
      <div className="flex items-start gap-3">
        <span className="grid size-11 shrink-0 place-items-center rounded-full bg-[#5f9277] text-sm font-bold text-white">{initials(a.customer)}</span>
        <div className="min-w-0 flex-1">
          <p className="text-sm text-muted">{a.customer} asked for a refund</p>
          <p className="text-3xl font-extrabold tracking-[-0.04em]">{usd(a.amount)}</p>
          <p className="text-sm text-muted">for order <b className="text-ink">{a.order_id}</b></p>
        </div>
        {!pending && (
          <Pill tone={a.status === "approved" ? "ok" : a.status === "rejected" ? "no" : "wait"}>
            {a.status === "processing" ? "Paying out…" : a.status === "approved" ? `Approved${a.decided_by ? ` by ${person(a.decided_by)}` : ""}` : a.status === "rejected" ? "Rejected" : a.status}
          </Pill>
        )}
      </div>
      {a.reason && <p className="rounded-2xl bg-bg px-4 py-3 text-sm">&ldquo;{a.reason.replace(/^customer asked:\s*/i, "")}&rdquo;</p>}
      {pending && (
        <>
          <p className="text-xs text-muted">
            <span className="font-semibold text-accent">Why you&apos;re seeing this:</span> the AI can refund up to $50 on its own. This is more, so it paused and is waiting for you.
          </p>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={!signedIn} onClick={() => onDecide(a.id, "approve")}
              className="rounded-full bg-ink px-6 py-3 text-sm font-semibold text-bg transition hover:bg-ok disabled:cursor-not-allowed disabled:opacity-40">
              Approve refund
            </button>
            <button type="button" disabled={!signedIn} onClick={() => onDecide(a.id, "reject")}
              className="rounded-full border border-line px-6 py-3 text-sm font-semibold transition hover:border-bad hover:text-bad disabled:cursor-not-allowed disabled:opacity-40">
              Reject
            </button>
            {!signedIn && <span className="self-center text-xs text-muted">Sign in above to decide</span>}
          </div>
        </>
      )}
    </article>
  );
}

export default function Staff() {
  const { api, staff, setCustomer, openChat } = useApp();
  const router = useRouter();
  const qc = useQueryClient();
  const [note, setNote] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const { data, error } = useAppState({ poll: (d) => (d?.approvals.some((a) => a.status === "processing") ? 1500 : false) });
  const { data: health } = useHealth();
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api<Metrics>("/api/metrics?days=7"), refetchInterval: 15_000 });

  async function decide(id: number, decision: "approve" | "reject") {
    setNote(null);
    try {
      await api(`/api/approvals/${id}`, { method: "POST", token: staff?.token, body: { decision } });
      setNote({ tone: "ok", text: decision === "approve" ? "Approved. The refund is being paid back to the customer." : "Rejected. No money moved, and the customer will be told." });
    } catch (e) {
      setNote({ tone: "bad", text: (e as Error).message });
    }
    await Promise.all([qc.invalidateQueries({ queryKey: ["state"] }), qc.invalidateQueries({ queryKey: ["metrics"] })]);
  }

  // Demo shortcut: become Maya and have her refund question ready in the chat (she presses Send).
  function makeTestRequest() {
    setCustomer("C2");
    router.push("/");
    window.setTimeout(() => openChat("Refund order O2001", false), 400);
  }

  if (error) return <Note tone="bad">{(error as Error).message}</Note>;
  if (!data) return <p className="text-muted">Loading…</p>;
  const m = metrics.data;
  const waiting = data.approvals.filter((a) => a.status === "pending");
  const decided = data.approvals.filter((a) => a.status !== "pending").reverse();
  const step: 1 | 2 | 3 = !staff ? 1 : waiting.length ? 3 : 2;

  return (
    <section className="flex flex-col gap-10">
      <header className="flex flex-col gap-3">
        <p className="text-xs font-bold uppercase tracking-[0.3em] text-accent">• Staff</p>
        <h1 className="text-5xl leading-none md:text-6xl">Support <span className="font-accent font-normal italic text-accent">desk.</span></h1>
        <p className="max-w-2xl text-lg text-muted">
          The AI answers customers on its own. When something needs a person, like a refund over $50, it pauses and the request lands here for you to decide.
        </p>
      </header>

      <ol className="grid gap-3 md:grid-cols-3">
        <Step n={1} title="Sign in" text="As the support manager." state={step === 1 ? "now" : "done"} />
        <Step n={2} title="Review requests" text="See who asked, how much, and why." state={step === 2 ? "now" : step === 3 ? "done" : "later"} />
        <Step n={3} title="Approve or reject" text="The AI carries on with your decision." state={step === 3 ? "now" : "later"} />
      </ol>

      <div className="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
        <div className="flex min-w-0 flex-col gap-5">
          <SignIn />
          {note && <Note tone={note.tone}>{note.text}</Note>}

          <div className="flex items-baseline justify-between">
            <h2 className="text-2xl">Needs your decision</h2>
            <span className="text-sm text-muted">{waiting.length} waiting</span>
          </div>
          {waiting.length ? (
            waiting.map((a) => <RequestCard key={a.id} a={a} signedIn={!!staff} onDecide={decide} />)
          ) : (
            <div className="flex flex-col items-start gap-3 rounded-3xl border border-dashed border-line p-6">
              <b className="text-lg">All clear. Nothing needs you right now.</b>
              <p className="text-sm text-muted">
                To see a request arrive, become Maya Brooks and ask for a refund on her $189 order. It&apos;s over the AI&apos;s limit, so it comes here.
              </p>
              <button type="button" onClick={makeTestRequest} className="rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-bg transition hover:bg-accent">
                Create a test request →
              </button>
            </div>
          )}

          {decided.length > 0 && (
            <>
              <h2 className="mt-4 text-2xl">Already decided</h2>
              {decided.map((a) => <RequestCard key={a.id} a={a} signedIn={!!staff} onDecide={decide} />)}
            </>
          )}
        </div>

        <aside className="flex min-w-0 flex-col gap-5">
          <div className="rounded-3xl border border-line bg-surface p-5">
            <h2 className="text-xl">This week</h2>
            <p className="text-sm text-muted">Across all visitors, last {m?.window_days ?? 7} days.</p>
            <div className="mt-4 grid grid-cols-2 gap-2">
              <Stat value={m?.conversations ?? "–"} label="conversations" />
              <Stat value={m ? pct(m.containment_rate) : "–"} label="solved by the AI alone" />
              <Stat value={m ? pct(m.escalation_rate) : "–"} label="passed to a person" />
              <Stat value={m?.injection_flags ?? "–"} label="tricks blocked" />
            </div>
          </div>

          <div className="rounded-3xl border border-line bg-surface p-5">
            <h2 className="text-xl">Passed to the team</h2>
            <p className="text-sm text-muted">Problems the AI handed to a person, like damaged items.</p>
            <ul className="mt-3 flex flex-col divide-y divide-line">
              {data.tickets.length ? data.tickets.map((t) => (
                <li key={String(t.id)} className="py-3 text-sm">
                  <b>{t.order_id ? `Order ${t.order_id}` : "General"}</b>
                  <span className="block text-muted">{String(t.summary)}</span>
                </li>
              )) : <li className="py-3 text-sm text-muted">None yet.</li>}
            </ul>
          </div>
        </aside>
      </div>

      {/* Everything an engineer would want, kept out of the way. */}
      <details className="group rounded-3xl border border-line bg-surface">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4 p-5">
          <span>
            <b className="block">Technical details</b>
            <span className="text-sm text-muted">For engineers: audit log, success targets, system health, payments and every AI run.</span>
          </span>
          <span className="text-2xl text-muted transition group-open:rotate-45" aria-hidden>+</span>
        </summary>
        <div className="grid gap-6 border-t border-line p-5 lg:grid-cols-2">
          <div className="flex min-w-0 flex-col gap-2">
            <h3 className="text-lg">Audit log</h3>
            <Table head={["when", "who", "role", "action", "detail"]} rows={data.audit.map((a) => [String(a.created_at).slice(11), a.actor, a.role, a.action, a.detail])} />
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <h3 className="text-lg">Success targets</h3>
            {m ? (
              <Table head={["target", "goal", "now", ""]}
                rows={m.targets.map((t) => [t.meaning, t.target.replace(/_/g, " "), fmt(t.metric, t.value),
                  t.met == null ? <Pill key={t.metric}>no data</Pill> : t.met ? <Pill key={t.metric} tone="ok">met</Pill> : <Pill key={t.metric} tone="no">missed</Pill>])} />
            ) : <p className="text-sm text-muted">Loading…</p>}
            {m && <p className="text-xs text-muted">By agent: {Object.entries(m.by_agent).map(([a, n]) => `${a} ${n}`).join(" · ") || "none yet"} · tool calls blocked by rules: {m.rule_blocks}</p>}
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <h3 className="text-lg">System health{health ? ` · v${health.version}` : ""}</h3>
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
                <p className="text-xs text-muted">{health.mode} · real-model calls today {health.ai_calls_today}/{health.ai_daily_cap} · live sandboxes {health.sessions}</p>
                <GatewayTable providers={health.gateway.providers} />
              </>
            )}
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <h3 className="text-lg">Money out</h3>
            <Table head={["id", "order", "amount", "by", "provider id", "status"]}
              rows={data.refunds.map((r) => [r.id, r.order_id, cents(r.amount_cents ?? 0), r.via, r.provider_refund_id, r.status])} />
          </div>
          <div className="flex min-w-0 flex-col gap-2 lg:col-span-2">
            <h3 className="text-lg">Every AI run in this sandbox</h3>
            <Table head={["id", "agent", "ended", "steps", "tokens", "tools", "answered by", "ms"]}
              rows={data.runs.map((r) => [r.id, r.agent, r.stopped, r.steps, r.tokens, r.tools || "none", `${r.provider ?? ""}${r.route ? ` / ${r.route}` : ""}`, r.millis])} />
          </div>
        </div>
      </details>
    </section>
  );
}
