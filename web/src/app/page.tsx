"use client";

import Link from "next/link";
import { useApp, useHealth } from "@/components/providers";
import { Button, Eyebrow } from "@/components/ui";
import { usd } from "@/lib/api";
import { GLYPHS, PRODUCTS } from "@/lib/products";

function Glyph({ name }: { name: string }) {
  return <svg viewBox="0 0 100 100" aria-hidden className="size-28" dangerouslySetInnerHTML={{ __html: GLYPHS[name] }} />;
}

export default function Shop() {
  const { openChat } = useApp();
  const { data: health } = useHealth();
  const mode = !health ? "Checking assistant status" : health.mode.includes("gemini")
    ? "Support assistant online: Gemini, with an offline backup"
    : "Support assistant online: built-in offline assistant";

  return (
    <div className="flex flex-col gap-14">
      <section className="grid items-center gap-8 md:grid-cols-[1.2fr_1fr]">
        <div className="flex flex-col gap-5">
          <Eyebrow>Brightwood Goods</Eyebrow>
          <h1 className="text-4xl font-bold leading-tight md:text-5xl">Calm things for the rooms you live in.</h1>
          <p className="max-w-xl text-lg text-muted">
            A pretend home goods store with a real AI support team. Nothing here can be bought: every demo customer already has orders,
            and the support agents help with them, from tracking and cancelling to returns and refunds.
          </p>
          <div className="flex flex-wrap gap-3">
            <Button variant="solid" onClick={() => openChat()}>Talk to support</Button>
            <Link href="/how-it-works" className="inline-flex items-center rounded-xl border border-line bg-surface px-4 py-2.5 text-sm font-semibold hover:bg-surface-2">
              See how it works
            </Link>
          </div>
          <p className="flex items-center gap-2 text-sm text-muted">
            <span className={`size-2 rounded-full ${health ? "bg-ok" : "bg-warn"}`} aria-hidden />
            {mode}
          </p>
        </div>
        <div className="relative hidden h-72 md:block" aria-hidden>
          <div className="absolute left-6 top-4 rotate-[-6deg] rounded-3xl bg-[linear-gradient(150deg,#dfe8f3,#a9c2e2)] p-4 shadow-card"><Glyph name="lamp" /></div>
          <div className="absolute right-4 top-16 rotate-[5deg] rounded-3xl bg-[linear-gradient(150deg,#f3e3d8,#e0b9a3)] p-4 shadow-card"><Glyph name="throw" /></div>
          <div className="absolute bottom-0 left-28 rounded-3xl bg-[linear-gradient(150deg,#dcefe0,#9fd0ad)] p-4 shadow-card"><Glyph name="planter" /></div>
        </div>
      </section>

      <section aria-labelledby="how-h" className="flex flex-col gap-4 rounded-2xl border border-line bg-surface p-5 shadow-card">
        <div>
          <Eyebrow>How this demo works</Eyebrow>
          <h2 id="how-h" className="mt-1 text-2xl font-bold">Three things to try</h2>
        </div>
        <ol className="grid gap-4 md:grid-cols-3">
          {[
            ["Pick who you are", "Use the “You are” menu at the top. Sam, Priya and Alex each have different orders: delivered, shipped, still processing."],
            ["Ask support about an order", "Track it, cancel it, ask for a return label or a refund, or ask a policy question. Try Priya with “Refund order O2001”."],
            ["Switch to Staff", "Press Staff at the top to approve or reject the refunds the AI wasn’t allowed to give on its own (anything over $50)."],
          ].map(([title, text], n) => (
            <li key={title} className="flex gap-3">
              <span className="grid size-8 shrink-0 place-items-center rounded-full bg-brand-soft font-mono text-sm font-bold text-brand">{n + 1}</span>
              <div className="min-w-0"><h3 className="font-semibold">{title}</h3><p className="text-sm text-muted">{text}</p></div>
            </li>
          ))}
        </ol>
      </section>

      <section className="flex flex-col gap-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <Eyebrow>The catalogue</Eyebrow>
            <h2 className="mt-1 text-2xl font-bold">Items in the demo orders</h2>
          </div>
          <p className="max-w-md text-sm text-muted">These are the products the demo customers have ordered. They’re here for context; ask support about the return rules for any of them.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {PRODUCTS.map((p) => (
            <article key={p.name} className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
              <div className="relative grid h-44 place-items-center" style={{ background: `linear-gradient(150deg, ${p.colors[0]}, ${p.colors[1]})` }}>
                <Glyph name={p.glyph} />
                {p.clearance && <span className="absolute left-3 top-3 rounded-full bg-bad px-2.5 py-0.5 text-xs font-bold text-white">Final sale</span>}
              </div>
              <div className="flex flex-col gap-1 p-4">
                <h3 className="font-semibold">{p.name}</h3>
                <p className="text-sm text-muted">{p.tagline}</p>
                <div className="mt-2 flex items-center justify-between">
                  <span className="font-display text-lg font-bold">{usd(p.price)}</span>
                  <Button size="sm" onClick={() => openChat(p.clearance ? `Can I return the ${p.name.toLowerCase()}?` : `What is your return policy for the ${p.name.toLowerCase()}?`, true)}>
                    Ask about returns
                  </Button>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

      <footer className="border-t border-line pt-6 text-sm text-muted">
        Brightwood Goods is a made-up store: customers, orders and products are invented. The support agents, their rules and their records
        are real software, built to show how an AI support team can be made safe to run.
      </footer>
    </div>
  );
}
