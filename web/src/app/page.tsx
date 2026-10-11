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
            A small home goods store with an unusual support team: a supervisor AI that hands each question to a policy, orders or billing
            specialist, reads the store&apos;s real help articles, and sends large refunds to a person.
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

      <section className="flex flex-col gap-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <Eyebrow>The shop</Eyebrow>
            <h2 className="mt-1 text-2xl font-bold">New this month</h2>
          </div>
          <p className="max-w-md text-sm text-muted">Brightwood is a fictional store, so nothing here can be bought. Ask support about any item.</p>
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
                    Ask support
                  </Button>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

      <footer className="border-t border-line pt-6 text-sm text-muted">
        Brightwood Goods is a made-up store: customers, orders and products are invented. The support agents, their rules and their records
        are real software, built to show how an AI support team can be made safe to run. <Link href="/staff" className="font-semibold text-brand underline">Staff sign-in</Link>
      </footer>
    </div>
  );
}
