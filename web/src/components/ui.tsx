import type { ReactNode } from "react";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

type Tone = "ok" | "wait" | "no" | "brand" | "neutral";
const TONES: Record<Tone, string> = {
  ok: "bg-ok-soft text-ok",
  wait: "bg-warn-soft text-warn",
  no: "bg-bad-soft text-bad",
  brand: "bg-brand-soft text-brand",
  neutral: "bg-surface-2 text-muted",
};

export function Pill({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 font-sans text-xs font-semibold tracking-normal", TONES[tone], className)}>
      {children}
    </span>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-md border border-line bg-surface p-5 shadow-card", className)}>{children}</div>;
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <div className="text-[0.7rem] font-semibold uppercase tracking-[0.22em] text-muted">{children}</div>;
}

export function Note({ tone = "info", children }: { tone?: "info" | "ok" | "bad"; children: ReactNode }) {
  const style = { info: "border-brand/30 bg-brand-soft text-ink", ok: "border-ok/30 bg-ok-soft text-ink", bad: "border-bad/30 bg-bad-soft text-ink" }[tone];
  return <div className={cx("rounded-md border px-4 py-3 text-sm", style)}>{children}</div>;
}

export function Button({
  children,
  variant = "outline",
  size = "md",
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "solid" | "outline" | "ghost" | "danger"; size?: "sm" | "md" }) {
  const v = {
    solid: "bg-brand text-brand-ink hover:opacity-90 border-transparent",
    outline: "border-line bg-surface hover:bg-surface-2",
    ghost: "border-transparent hover:bg-surface-2",
    danger: "border-transparent bg-bad text-white hover:opacity-90",
  }[variant];
  const s = size === "sm" ? "px-3 py-1.5 text-sm" : "px-4 py-2.5 text-sm";
  return (
    <button
      type="button"
      className={cx("inline-flex items-center justify-center gap-2 rounded-md border font-semibold transition disabled:cursor-not-allowed disabled:opacity-50", v, s, className)}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Table({ head, rows, empty = "Nothing yet." }: { head: string[]; rows: (string | number | null | undefined | ReactNode)[][]; empty?: string }) {
  if (!rows.length) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <div className="max-w-full overflow-x-auto rounded-md border border-line">
      <table className="w-full min-w-max border-collapse text-left text-sm">
        <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
          <tr>{head.map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-line align-top">
              {r.map((c, j) => <td key={j} className="max-w-[28rem] px-3 py-2 [overflow-wrap:anywhere]">{c ?? ""}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Stat({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className="rounded-md bg-surface-2 px-4 py-3">
      <div className="font-display text-xl font-bold">{value}</div>
      <div className="text-xs text-muted">{label}</div>
    </div>
  );
}

export function ScoreBar({ score }: { score: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2" aria-hidden>
      <i className="block h-full rounded-full bg-brand" style={{ width: `${Math.min(100, Math.max(2, score * 160))}%` }} />
    </div>
  );
}

/** One retrieved help passage with its match score (help search and the inspector). */
export function Passage({ id, score, text, rank }: { id: string; score: number; text: string; rank?: number }) {
  return (
    <div className="rounded-md border border-line p-3">
      <div className="mb-1 flex justify-between font-mono text-xs">
        <span className="text-brand">{rank ? `${rank}. ` : ""}{id}</span>
        <span>{score.toFixed(2)}</span>
      </div>
      <ScoreBar score={score} />
      <p className="mt-2 text-sm">{text}</p>
    </div>
  );
}

/** Per-provider gateway stats (staff health and the inspector). */
export function GatewayTable({ providers }: { providers: Record<string, { calls: number; failures: number; skipped_open: number; avg_seconds: number }> }) {
  return <Table head={["provider", "calls", "failures", "skipped", "avg s"]} rows={Object.entries(providers).map(([n, p]) => [n, p.calls, p.failures, p.skipped_open, p.avg_seconds])} />;
}

// What happened to the customer's request, in plain words.
const STATE_LABEL: Record<string, [string, Tone]> = {
  ok: ["Resolved", "ok"],
  waiting: ["Waiting for a manager", "wait"],
  blocked: ["Not allowed by store rules", "no"],
  refused: ["Declined", "no"],
  stopped: ["Stopped safely", "no"],
};
export function StatePill({ state }: { state: string }) {
  const [label, tone] = STATE_LABEL[state] ?? [state, "neutral" as Tone];
  return <Pill tone={tone}>{label}</Pill>;
}
