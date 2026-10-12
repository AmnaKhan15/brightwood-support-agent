"use client";

import { motion } from "motion/react";
import dynamic from "next/dynamic";
import { useApp, useHealth } from "./providers";
import { Magnetic, RevealWords, useSpotlight } from "./motion";
import { AGENTS, type AgentId } from "./three/agents";

// WebGL only runs in the browser, so the scene loads after the page has painted.
const AgentScene = dynamic(() => import("./three/agent-scene"), {
  ssr: false,
  loading: () => <div className="size-full animate-pulse rounded-full bg-[radial-gradient(circle,rgb(45_212_191/0.18),transparent_60%)]" />,
});

// One question per specialist, so clicking an agent shows it at work.
const ASK: Record<AgentId, string> = {
  policy: "Can I return a clearance item?",
  orders: "Where are my orders?",
  billing: "I'd like a refund for order O1001",
};

const isAgent = (a: string | null | undefined): a is AgentId => AGENTS.some((x) => x.id === a);

export function Hero() {
  const { openChat, inspect } = useApp();
  const { data: health } = useHealth();
  const spot = useSpotlight<HTMLElement>();
  const live = !!health?.mode.includes("gemini");
  const agent = isAgent(inspect?.agent) ? inspect.agent : null;
  const meta = AGENTS.find((a) => a.id === agent);
  const tools = inspect?.steps.map((s) => s.tool).filter(Boolean) ?? [];

  return (
    <section
      ref={spot}
      className="hero-stage relative isolate -mx-4 -mt-8 overflow-hidden px-5 pb-10 pt-14 text-white sm:-mx-6 sm:px-8 lg:mx-0 lg:mt-0 lg:rounded-[28px] lg:px-14 lg:pt-16"
    >
      {/* Light: two slow aurora blobs, a fine grid that fades out, and a glow that follows the cursor. */}
      <div aria-hidden className="aurora pointer-events-none absolute -left-40 -top-40 -z-10 size-[620px] rounded-full bg-teal-400/25 blur-[120px]" />
      <div aria-hidden className="aurora aurora-2 pointer-events-none absolute -bottom-52 right-0 -z-10 size-[560px] rounded-full bg-violet-500/20 blur-[130px]" />
      <div aria-hidden className="hero-grid pointer-events-none absolute inset-0 -z-10" />
      <div aria-hidden className="hero-spot pointer-events-none absolute inset-0 -z-10" />

      <div className="grid items-center gap-6 lg:min-h-[640px] lg:grid-cols-[1.05fr_1fr]">
        <div className="relative z-10 flex flex-col gap-7">
          <motion.span
            initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}
            className="inline-flex w-fit items-center gap-2 rounded-full border border-white/15 bg-white/[0.06] px-3.5 py-1.5 text-xs font-medium text-white/80 backdrop-blur-md"
          >
            <span className="relative flex size-2">
              <span className={`absolute inline-flex size-full animate-ping rounded-full opacity-70 ${live ? "bg-emerald-400" : "bg-amber-300"}`} />
              <span className={`relative inline-flex size-2 rounded-full ${live ? "bg-emerald-400" : "bg-amber-300"}`} />
            </span>
            {!health ? "Connecting to support…" : live ? "3 AI agents online · Gemini" : "3 AI agents online · backup model"}
          </motion.span>

          <h1 className="text-[2.9rem] font-semibold leading-[0.98] tracking-[-0.045em] sm:text-6xl xl:text-[5.4rem]">
            <RevealWords text="Calm things for home." />
            <br />
            <RevealWords text="Support that thinks." delay={0.35} wordClass={() => "text-gradient"} />
          </h1>

          <motion.p
            initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.75 }}
            className="max-w-lg text-lg leading-relaxed text-white/65"
          >
            Linen, oak, wool and stoneware. Behind the chat, a supervisor agent reads each message and hands it to a policy,
            orders or billing specialist. Ask something and watch the one that answers light up.
          </motion.p>

          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.9 }} className="flex flex-wrap items-center gap-3">
            <Magnetic>
              <a href="#shop" className="group inline-flex items-center gap-2 rounded-full bg-white px-6 py-3.5 text-sm font-semibold text-black shadow-[0_0_40px_-8px_rgb(255_255_255/0.6)] transition hover:shadow-[0_0_60px_-6px_rgb(255_255_255/0.8)]">
                Shop the collection
                <span className="transition group-hover:translate-x-0.5" aria-hidden>→</span>
              </a>
            </Magnetic>
            <Magnetic>
              <button type="button" onClick={() => openChat()} className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/[0.06] px-6 py-3.5 text-sm font-semibold text-white backdrop-blur-md transition hover:bg-white/[0.12]">
                Talk to support
              </button>
            </Magnetic>
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, scale: 0.92 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 1.4, ease: [0.22, 1, 0.36, 1], delay: 0.2 }}
          className="relative h-[380px] sm:h-[460px] lg:h-[620px]"
        >
          <AgentScene active={agent} pulse={inspect?.run_id ?? 0} onPick={(a) => openChat(ASK[a], true)} />
        </motion.div>
      </div>

      {/* What the agents just did, from the real response of the last chat message. */}
      <div className="relative z-10 mt-4 grid gap-3 border-t border-white/10 pt-6 text-sm sm:grid-cols-[auto_1fr_auto] sm:items-center">
        <span className="text-[0.68rem] font-semibold uppercase tracking-[0.24em] text-white/45">Last request</span>
        <span className="text-white/75" aria-live="polite">
          {inspect ? (
            <>
              <span className="mr-2 inline-block size-2 rounded-full align-middle" style={{ background: meta?.color ?? "#5eead4" }} />
              Supervisor routed it to the <b className="text-white">{meta ? `${meta.label.toLowerCase()} agent` : inspect.agent ?? "assistant"}</b>
              {tools.length ? <>, which called <span className="font-mono text-[0.8rem] text-white">{tools.join(" → ")}</span></> : null}
              <span className="text-white/45"> · {(inspect.millis / 1000).toFixed(1)} s</span>
            </>
          ) : (
            "Nothing yet. Click an agent above, or open the chat, and the one that answers lights up."
          )}
        </span>
        <span className="hidden text-white/45 sm:block">30-day returns · Free shipping over $75</span>
      </div>
    </section>
  );
}
