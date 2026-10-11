"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useApp, useHealth } from "@/components/providers";
import { Button, Eyebrow, Note } from "@/components/ui";
import { cents } from "@/lib/api";
import { GLYPHS, VISUALS } from "@/lib/products";
import type { CheckoutResult, Product } from "@/lib/types";

function Glyph({ name }: { name: string }) {
  return <svg viewBox="0 0 100 100" aria-hidden className="size-28" dangerouslySetInnerHTML={{ __html: GLYPHS[name] ?? "" }} />;
}

const STEPS = [
  ["Pick who you are", "Use the “You are” menu at the top. Sam, Priya and Alex each already have orders: delivered, shipped, still processing."],
  ["Buy something (optional)", "Press Buy on any item. It's a test payment, so no real money moves. The new order shows up in Your orders."],
  ["Ask support about an order", "Track it, cancel it, ask for a return label or a refund. Try Priya with “Refund order O2001”."],
  ["Switch to Staff", "Press Staff at the top to approve or reject refunds the AI wasn't allowed to give on its own (over $50)."],
];

export default function Shop() {
  const { api, openChat, customer, notify, ready } = useApp();
  const qc = useQueryClient();
  const router = useRouter();
  const { data: health } = useHealth();
  const products = useQuery({ queryKey: ["products"], queryFn: () => api<Product[]>("/api/products"), staleTime: Infinity });
  const [buying, setBuying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stripe = health?.payments === "stripe-test";
  const mode = !health ? "Checking assistant status" : health.mode.includes("gemini")
    ? "AI support online: Gemini answers, with a rule-based backup if it's unavailable"
    : "Backup assistant answering: no AI key is set, so simple built-in rules reply instead of Gemini";

  // Coming back from Stripe's page after pressing "back" there.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("checkout") === "cancelled") {
      notify("Checkout cancelled. Nothing was charged.");
      window.history.replaceState(null, "", "/");
    }
  }, [notify]);

  async function buy(p: Product) {
    setBuying(p.id);
    setError(null);
    try {
      const r = await api<CheckoutResult>("/api/checkout", { method: "POST", body: { customer, product_id: p.id } });
      if (r.mode === "stripe") {
        window.location.href = r.url; // Stripe's own checkout page takes the card
        return;
      }
      await qc.invalidateQueries({ queryKey: ["state"] });
      notify(`Order ${r.order_id} placed (simulated payment).`);
      router.push("/orders");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBuying(null);
    }
  }

  return (
    <div className="flex flex-col gap-14">
      <section className="grid items-center gap-8 md:grid-cols-[1.2fr_1fr]">
        <div className="flex flex-col gap-5">
          <Eyebrow>Brightwood Goods</Eyebrow>
          <h1 className="text-4xl font-bold leading-tight md:text-5xl">Calm things for the rooms you live in.</h1>
          <p className="max-w-xl text-lg text-muted">
            A demo home goods store with a real AI support team. Buy something with a test payment, then ask support to track it,
            cancel it, return it or refund it. Big refunds go to a person.
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
          <h2 id="how-h" className="mt-1 text-2xl font-bold">Four things to try</h2>
        </div>
        <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map(([title, text], n) => (
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
            <Eyebrow>The shop</Eyebrow>
            <h2 className="mt-1 text-2xl font-bold">Buy with a test payment</h2>
          </div>
          <p className="max-w-md text-sm text-muted">
            {stripe
              ? "Payments run in Stripe test mode. On Stripe's page use card 4242 4242 4242 4242, any future date and any CVC. No real money moves."
              : "Payments are simulated on this server (no Stripe key is set), so Buy completes instantly with no card."}
          </p>
        </div>
        {error && <Note tone="bad">{error}</Note>}
        {products.isLoading && <p className="text-muted">Loading the shop…</p>}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {products.data?.map((p) => {
            const look = VISUALS[p.id]?.colors ?? ["#eee", "#ddd"];
            return (
              <article key={p.id} className="flex flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
                <div className="relative grid h-44 place-items-center" style={{ background: `linear-gradient(150deg, ${look[0]}, ${look[1]})` }}>
                  <Glyph name={p.id} />
                  {p.final_sale && <span className="absolute left-3 top-3 rounded-full bg-bad px-2.5 py-0.5 text-xs font-bold text-white">Final sale</span>}
                </div>
                <div className="flex flex-1 flex-col gap-1 p-4">
                  <h3 className="font-semibold">{p.name}</h3>
                  <p className="text-sm text-muted">{p.tagline}</p>
                  <p className="text-xs text-muted">{p.shipping_cents ? `+ ${cents(p.shipping_cents)} shipping` : "Free shipping"}</p>
                  <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-3">
                    <span className="font-display text-lg font-bold">{cents(p.price_cents)}</span>
                    <div className="flex gap-2">
                      <Button size="sm" variant="ghost" onClick={() => openChat(p.final_sale ? `Can I return the ${p.name.toLowerCase()}?` : `What is your return policy for the ${p.name.toLowerCase()}?`, true)}>
                        Ask about returns
                      </Button>
                      <Button size="sm" variant="solid" disabled={!ready || buying !== null} onClick={() => buy(p)}>
                        {buying === p.id ? "Opening…" : "Buy"}
                      </Button>
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <footer className="border-t border-line pt-6 text-sm text-muted">
        Brightwood Goods is a made-up store: customers and products are invented and payments are test-mode only. The support agents,
        their rules and their records are real software, built to show how an AI support team can be made safe to run.
      </footer>
    </div>
  );
}
