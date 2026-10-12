"use client";

import { AnimatePresence, motion } from "motion/react";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { useApp, useHealth } from "./providers";
import { Magnetic, RevealWords } from "./motion";
import { AGENTS, type AgentId } from "./three/agents";

// WebGL only runs in the browser, so the scene loads after the page has painted.
const AgentScene = dynamic(() => import("./three/agent-scene"), {
  ssr: false,
  loading: () => <div className="size-full animate-pulse bg-[radial-gradient(circle_at_60%_50%,rgb(222_93_53/0.14),transparent_55%)]" />,
});

// One question per specialist, so clicking an agent shows it at work.
const ASK: Record<AgentId, string> = {
  policy: "Can I return a clearance item?",
  orders: "Where are my orders?",
  billing: "I'd like a refund for order O1001",
};

const isAgent = (a: string | null | undefined): a is AgentId => AGENTS.some((x) => x.id === a);

function ArrowUpRight({ className }: { className?: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden className={className}>
      <path d="M7 17 17 7M8 7h9v9" />
    </svg>
  );
}

export function Hero() {
  const { openChat, inspect } = useApp();
  const { data: health } = useHealth();
  const [reel, setReel] = useState(false);

  // 100vw includes the scrollbar; publish its width so the full-bleed section is exactly as wide as the page.
  useEffect(() => {
    const measure = () => document.documentElement.style.setProperty("--sbw", `${window.innerWidth - document.documentElement.clientWidth}px`);
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  const live = !!health?.mode.includes("gemini");
  const agent = isAgent(inspect?.agent) ? inspect.agent : null;
  const meta = AGENTS.find((a) => a.id === agent);
  const tools = inspect?.steps.map((s) => s.tool).filter(Boolean) ?? [];
  const ask = (a: AgentId) => {
    setReel(false);
    openChat(ASK[a], true);
  };

  return (
    <>
      {/* Edge to edge: the section spans the whole viewport, wider than the page column it sits in. */}
      <section className="relative isolate left-1/2 -mt-8 flex min-h-[calc(100svh-4rem)] w-[calc(100vw-var(--sbw,0px))] -translate-x-1/2 flex-col overflow-hidden bg-bg pb-8 pt-10">
        {/* Soft cream fades keep the text readable; the artwork in the middle and right stays clear. */}
        <div aria-hidden className="pointer-events-none absolute inset-y-0 left-0 z-0 hidden w-[max(42%,calc((100%-1400px)/2+640px))] bg-gradient-to-r from-bg via-bg/90 to-transparent lg:block" />
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 z-0 h-28 bg-gradient-to-b from-bg via-bg/60 to-transparent lg:h-36" />
        <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 z-0 h-40 bg-gradient-to-t from-bg via-bg/80 to-transparent lg:h-48" />
        <div aria-hidden className="aurora pointer-events-none absolute right-[18%] top-1/4 -z-20 size-[520px] rounded-full bg-accent/15 blur-[120px]" />

        {/* Same column as the header and the page below, so the text lines up with them.
            Not positioned itself, so the artwork's absolute layer still spans the whole section. */}
        <div className="mx-auto flex w-full max-w-[1400px] flex-1 flex-col justify-between px-4 sm:px-6 lg:px-10">
        <div className="relative z-10 my-auto flex max-w-xl flex-col gap-7 py-6">
          <motion.p initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}
            className="text-xs font-bold uppercase tracking-[0.3em] text-accent">
            • Home goods • AI support • Real people
          </motion.p>

          <h1 className="text-[3.3rem] font-extrabold leading-[0.95] tracking-[-0.05em] sm:text-7xl xl:text-[6.4rem]">
            <RevealWords text="Calm Things," />
            <br />
            <RevealWords text="Smart Support." delay={0.3} wordClass={() => "font-accent font-normal italic tracking-[-0.02em] text-accent"} />
          </h1>

          <motion.p initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.7 }}
            className="max-w-md text-lg leading-relaxed text-muted">
            Linen, oak, wool and stoneware, looked after by a team of AI agents that track, return and refund in seconds, with
            real people for the big decisions.
          </motion.p>

          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.85 }} className="flex flex-wrap items-center gap-3">
            <Magnetic>
              <a href="#shop" className="group inline-flex items-center gap-2.5 rounded-full bg-ink py-3.5 pl-6 pr-3.5 text-sm font-semibold text-bg transition hover:bg-accent">
                Shop the collection
                <span className="relative grid size-7 place-items-center overflow-hidden rounded-full bg-bg/15">
                  <ArrowUpRight className="transition duration-300 group-hover:-translate-y-5 group-hover:translate-x-5" />
                  <ArrowUpRight className="absolute -translate-x-5 translate-y-5 transition duration-300 group-hover:translate-x-0 group-hover:translate-y-0" />
                </span>
              </a>
            </Magnetic>
            <Magnetic>
              <button type="button" onClick={() => setReel(true)}
                className="group inline-flex items-center gap-2.5 rounded-full border border-ink/80 px-5 py-3.5 text-sm font-semibold transition hover:bg-ink hover:text-bg">
                <span className="grid size-5 place-items-center rounded-full bg-accent text-white">
                  <svg width="8" height="9" viewBox="0 0 8 9" fill="currentColor" aria-hidden><path d="M0 0v9l8-4.5z" /></svg>
                </span>
                Watch the agents
              </button>
            </Magnetic>
          </motion.div>

          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.8, delay: 1.05 }} className="flex items-center gap-4">
            <div className="flex -space-x-3" aria-hidden>
              {[["S", "#d9a441"], ["P", "#5f9277"], ["A", "#8a7f74"]].map(([l, c]) => (
                <span key={l} className="grid size-10 place-items-center rounded-full text-sm font-bold text-white ring-[3px] ring-bg" style={{ background: c }}>{l}</span>
              ))}
              <span className="grid size-10 place-items-center rounded-full bg-accent text-[0.7rem] font-extrabold text-white ring-[3px] ring-bg">AI</span>
            </div>
            <p className="text-sm leading-snug text-muted">
              <b className="text-ink">3 demo customers, 4 AI agents</b>
              <br />
              <span className="inline-flex items-center gap-1.5">
                <span className={`size-1.5 rounded-full ${live ? "bg-ok" : "bg-warn"}`} />
                {!health ? "Connecting…" : live ? "Support online · Gemini" : "Support online · backup model"}
              </span>
            </p>
          </motion.div>
        </div>

        {/* The artwork: the live agent graph. Behind the text on large screens, below it on small ones. */}
        <motion.div initial={{ opacity: 0, scale: 0.94 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 1.4, ease: [0.22, 1, 0.36, 1], delay: 0.15 }}
          className="relative -mx-4 h-[380px] sm:-mx-6 sm:h-[460px] lg:absolute lg:inset-y-0 lg:right-0 lg:-z-10 lg:mx-0 lg:h-auto lg:w-[68%]">
          <AgentScene active={agent} pulse={inspect?.run_id ?? 0} onPick={ask} />
        </motion.div>

        {/* What the agents just did, from the real response of the last chat message. */}
        <div className="relative z-10 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-t border-line pt-5 text-sm">
          <span className="text-muted" aria-live="polite">
            <span className="mr-3 text-[0.68rem] font-bold uppercase tracking-[0.24em] text-ink">Last request</span>
            {inspect ? (
              <>
                <span className="mr-1.5 inline-block size-2 rounded-full align-middle" style={{ background: meta?.color ?? "var(--accent)" }} />
                Routed to the <b className="text-ink">{meta ? `${meta.label.toLowerCase()} agent` : inspect.agent ?? "assistant"}</b>
                {tools.length ? <>, which called <span className="font-mono text-[0.8rem] text-ink">{tools.join(" → ")}</span></> : null}
                <span> · {(inspect.millis / 1000).toFixed(1)} s</span>
              </>
            ) : (
              "Nothing yet. Click an agent, and the one that answers lights up."
            )}
          </span>
          <span className="hidden text-muted sm:block">30-day returns · Free shipping over $75</span>
        </div>
        </div>
      </section>

      <AgentReel open={reel} onClose={() => setReel(false)} onAsk={ask} active={agent} pulse={inspect?.run_id ?? 0} />
    </>
  );
}

/** Fullscreen view of the agent graph, with a one-click question for each specialist. Esc or the button closes it. */
function AgentReel({ open, onClose, onAsk, active, pulse }: { open: boolean; onClose: () => void; onAsk: (a: AgentId) => void; active: AgentId | null; pulse: number }) {
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div role="dialog" aria-modal="true" aria-label="The support agents, live" data-lenis-prevent
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.3 }}
          className="fixed inset-0 z-[60] flex flex-col bg-bg/80 backdrop-blur-xl" onClick={onClose}>
          <motion.div initial={{ scale: 0.96, y: 20 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.96, y: 20 }} transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
            className="relative m-3 flex flex-1 flex-col overflow-hidden rounded-3xl border border-line bg-surface shadow-2xl sm:m-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between gap-4 p-6 sm:p-8">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.3em] text-accent">• Live agent graph</p>
                <h2 className="mt-2 text-3xl sm:text-4xl">The team, <span className="font-accent font-normal italic text-accent">at work.</span></h2>
                <p className="mt-2 max-w-lg text-sm text-muted">The supervisor reads each message and routes it to one specialist. Pick a question to send it, and watch which one lights up.</p>
              </div>
              <button type="button" onClick={onClose} aria-label="Close" className="grid size-11 shrink-0 place-items-center rounded-full border border-line transition hover:bg-ink hover:text-bg">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M18 6 6 18M6 6l12 12" /></svg>
              </button>
            </div>
            <div className="relative min-h-0 flex-1">
              <AgentScene active={active} pulse={pulse} onPick={onAsk} />
            </div>
            <div className="flex flex-wrap justify-center gap-2 p-6">
              {AGENTS.map((a) => (
                <button key={a.id} type="button" onClick={() => onAsk(a.id)}
                  className="inline-flex items-center gap-2 rounded-full border border-line bg-bg px-4 py-2.5 text-sm font-semibold transition hover:border-ink">
                  <span className="size-2 rounded-full" style={{ background: a.color }} />
                  {a.label}: &ldquo;{ASK[a.id]}&rdquo;
                </button>
              ))}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
