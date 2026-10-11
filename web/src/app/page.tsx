"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useApp, useHealth } from "@/components/providers";
import { Button, Eyebrow, Note } from "@/components/ui";
import { cents } from "@/lib/api";
import { HERO_PHOTO, PHOTOS } from "@/lib/products";
import type { CheckoutResult, Product } from "@/lib/types";

const STEPS = [
  ["Pick who you are", "Use “You are” at the top. Sam, Priya and Alex each already have orders: delivered, shipped and still processing."],
  ["Buy something", "Optional. Press Buy on any piece. It’s a test payment, so no real money moves, and the order appears in Your orders."],
  ["Ask support", "Track an order, cancel it, request a return label or a refund. Try Priya with “Refund order O2001”."],
  ["Switch to Staff", "Approve or reject the refunds the AI wasn’t allowed to give on its own: anything over $50."],
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
  const status = !health ? "Checking the support assistant…" : health.mode.includes("gemini")
    ? "AI support online · Gemini, with a rule-based backup"
    : "Backup assistant answering · no AI key set, so simple rules reply instead of Gemini";

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
        window.location.assign(r.url); // Stripe's own checkout page takes the card
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
    <div className="flex flex-col gap-20">
      <section className="grid items-center gap-10 lg:grid-cols-[1fr_1.15fr]">
        <div className="flex flex-col gap-6">
          <Eyebrow>Home goods · Est. 2026</Eyebrow>
          <h1 className="text-5xl leading-[1.05] md:text-6xl">
            Calm things for the <em className="italic">rooms</em> you live in.
          </h1>
          <p className="max-w-lg text-lg leading-relaxed text-muted">
            Linen, oak, wool and stoneware, made to be lived with. And when something isn&apos;t right, our support team, part AI and
            part people, sorts it out: tracking, returns, refunds.
          </p>
          <div className="flex flex-wrap gap-3">
            <a href="#shop" className="inline-flex items-center rounded-md bg-brand px-5 py-3 text-sm font-semibold text-brand-ink hover:opacity-90">
              Shop the collection
            </a>
            <Button onClick={() => openChat()} className="px-5 py-3">Get help</Button>
          </div>
          <p className="flex items-center gap-2 text-sm text-muted">
            <span className={`size-1.5 rounded-full ${health ? "bg-ok" : "bg-warn"}`} aria-hidden />
            {status}
          </p>
        </div>
        <div className="relative aspect-[4/3] w-full overflow-hidden rounded-md bg-surface-2">
          <Image src={HERO_PHOTO.src} alt={HERO_PHOTO.alt} fill priority sizes="(min-width: 1024px) 55vw, 100vw" className="object-cover" />
        </div>
      </section>

      <section aria-labelledby="how-h" className="flex flex-col gap-6 border-y border-line py-8">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="how-h" className="text-2xl">How this demo works</h2>
          <p className="text-sm text-muted">A pretend store with real software behind it.</p>
        </div>
        <ol className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map(([title, text], n) => (
            <li key={title} className="flex flex-col gap-1.5">
              <span className="font-display text-3xl text-muted">0{n + 1}</span>
              <h3 className="text-lg">{title}</h3>
              <p className="text-sm leading-relaxed text-muted">{text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section id="shop" className="flex scroll-mt-24 flex-col gap-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-col gap-2">
            <Eyebrow>The collection</Eyebrow>
            <h2 className="text-4xl">Pieces for every room</h2>
          </div>
          <p className="max-w-md text-sm leading-relaxed text-muted">
            {stripe
              ? "Checkout runs in Stripe test mode: use card 4242 4242 4242 4242, any future date and any CVC. No real money moves."
              : "Payments are simulated on this server (no Stripe key set), so Buy completes instantly without a card."}
          </p>
        </div>
        {error && <Note tone="bad">{error}</Note>}
        {products.isLoading && <p className="text-muted">Loading the collection…</p>}
        <div className="grid gap-x-6 gap-y-10 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {products.data?.map((p) => {
            const photo = PHOTOS[p.id];
            return (
              <article key={p.id} className="group flex flex-col gap-3">
                <div className="relative aspect-[4/5] overflow-hidden rounded-md bg-surface-2">
                  {photo && (
                    <Image src={photo.src} alt={photo.alt} fill sizes="(min-width: 1536px) 25vw, (min-width: 1024px) 33vw, (min-width: 640px) 50vw, 100vw"
                      className="object-cover transition duration-500 group-hover:scale-[1.03]" />
                  )}
                  {p.final_sale && (
                    <span className="absolute left-3 top-3 rounded-sm bg-surface/90 px-2 py-1 text-[0.65rem] font-semibold uppercase tracking-[0.18em] text-bad">
                      Final sale
                    </span>
                  )}
                </div>
                <div className="flex items-baseline justify-between gap-3">
                  <h3 className="text-xl">{p.name}</h3>
                  <span className="whitespace-nowrap text-base tabular-nums">{cents(p.price_cents)}</span>
                </div>
                <p className="-mt-2 text-sm text-muted">
                  {p.tagline} · {p.shipping_cents ? `${cents(p.shipping_cents)} shipping` : "free shipping"}
                </p>
                <div className="flex items-center gap-4">
                  <Button variant="solid" size="sm" className="px-5" disabled={!ready || buying !== null} onClick={() => buy(p)}>
                    {buying === p.id ? "Opening checkout…" : "Buy"}
                  </Button>
                  <button
                    type="button"
                    onClick={() => openChat(p.final_sale ? `Can I return the ${p.name.toLowerCase()}?` : `What is your return policy for the ${p.name.toLowerCase()}?`, true)}
                    className="text-sm text-muted underline decoration-line underline-offset-4 hover:text-ink"
                  >
                    Returns policy
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <footer className="flex flex-col gap-3 border-t border-line pt-8 text-sm text-muted">
        <p className="max-w-3xl">
          Brightwood Goods is a made-up store: customers and products are invented and payments are test-mode only. The support agents,
          their rules and their records are real software, built to show how an AI support team can be made safe to run.
        </p>
        <p className="text-xs">
          Photography from <Link href="https://unsplash.com" className="underline underline-offset-2" target="_blank" rel="noopener noreferrer">Unsplash</Link>{" "}
          by {[HERO_PHOTO, ...Object.values(PHOTOS)].map((p) => p.credit).join(", ")}.
        </p>
      </footer>
    </div>
  );
}
