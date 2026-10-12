"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Hero } from "@/components/hero";
import { InView, Tilt } from "@/components/motion";
import { useApp, useHealth } from "@/components/providers";
import { Button, Note } from "@/components/ui";
import { cents } from "@/lib/api";
import { HERO_PHOTO, PHOTOS } from "@/lib/products";
import type { CheckoutResult, Product } from "@/lib/types";

const MARQUEE = ["Linen", "Oak", "Wool", "Stoneware", "Free returns within 30 days", "Free shipping over $75", "Support in seconds", "Real people for big decisions"];

// The real agent graph (src/brightwood_support/agent.py): who does what, and which tools each one may call.
const TEAM = [
  { name: "Supervisor", color: "#faf7f2", job: "Reads every message first and hands it to the right specialist. If the model is down, keyword rules take over.", tools: ["route"] },
  { name: "Policy agent", color: "#5f9277", job: "Answers questions about the store's rules from the help articles, and shows the source.", tools: ["search_help", "escalate_to_human"] },
  { name: "Orders agent", color: "#d9a441", job: "Tracking, cancellations and return labels, for the signed-in customer's own orders only.", tools: ["get_order", "cancel_order", "send_return_label"] },
  { name: "Billing agent", color: "#de5d35", job: "Refunds up to $50 on its own. Anything larger pauses and waits for a manager's approval.", tools: ["get_order", "request_refund"] },
];

const STEPS = [
  ["Pick who you are", "Use “You are” at the top. Sam, Maya and Alex each already have orders: delivered, shipped and still processing."],
  ["Buy something", "Optional. Press Buy on any piece. It’s a test payment, so no real money moves, and the order appears in Your orders."],
  ["Ask support", "Track an order, cancel it, request a return label or a refund. Try Maya with “Refund order O2001”."],
  ["Switch to Staff", "Approve or reject the refunds the AI wasn’t allowed to give on its own: anything over $50."],
];

const TRY_ASKING = [
  ["Where are my orders?", "Lists your orders with their status"],
  ["Can I return a clearance item?", "Answers from the returns policy, with the source"],
  ["Cancel my processing order", "Cancels it and refunds you in full"],
  ["The lamp in O2001 arrived broken", "Hands it to a person with a ticket"],
];

// Answers taken from the store's help articles (data/help), the same text the assistant cites.
const FAQ = [
  ["How long do I have to return something?", "Most items can be returned within 30 days of delivery. The 30 days start on the delivery date, not the order date."],
  ["Can I return a clearance item?", "No. Items marked final sale, including clearance items and gift cards, cannot be returned."],
  ["When does my refund arrive?", "A refund goes back to the original payment method and arrives 5 to 7 business days after we receive the returned item."],
  ["Is shipping free?", "Shipping is free on orders over $75. Otherwise standard shipping is $6 and express is $15."],
  ["Who decides on a large refund?", "The assistant can refund up to $50 on its own. Anything larger is reviewed by a support manager before any money moves."],
];

function Section({ eyebrow, title, aside, children, id }: { eyebrow: string; title: string; aside?: React.ReactNode; children: React.ReactNode; id?: string }) {
  return (
    <section id={id} className="reveal flex scroll-mt-24 flex-col gap-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-2">
          <span className="text-[0.7rem] font-semibold uppercase tracking-[0.22em] text-muted">{eyebrow}</span>
          <h2 className="max-w-2xl text-4xl leading-tight md:text-5xl">{title}</h2>
        </div>
        {aside && <div className="max-w-md text-sm leading-relaxed text-muted">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

export default function Shop() {
  const { api, openChat, customer, notify, ready } = useApp();
  const qc = useQueryClient();
  const router = useRouter();
  const { data: health } = useHealth();
  const products = useQuery({ queryKey: ["products"], queryFn: () => api<Product[]>("/api/products"), staleTime: Infinity });
  const [buying, setBuying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stripe = health?.payments === "stripe-test";

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
    <div className="flex flex-col gap-24">
      <Hero />

      {/* A slow strip of what the store is about. Decorative, so screen readers skip the duplicate. */}
      <div className="marquee -my-12 overflow-hidden border-y border-line py-5" aria-hidden>
        <div className="marquee-track flex w-max gap-12 whitespace-nowrap text-sm font-semibold uppercase tracking-[0.3em] text-muted">
          {[...MARQUEE, ...MARQUEE].map((word, i) => (
            <span key={i} className="flex items-center gap-12">{word}<span className="text-line">✦</span></span>
          ))}
        </div>
      </div>

      <section className="hero-stage relative isolate -mx-4 overflow-hidden px-5 py-16 text-white sm:-mx-6 sm:px-8 lg:mx-0 lg:rounded-[28px] lg:px-14">
        <div aria-hidden className="aurora pointer-events-none absolute -right-40 -top-32 -z-10 size-[520px] rounded-full bg-accent/20 blur-[120px]" />
        <InView className="flex flex-wrap items-end justify-between gap-6">
          <div className="flex flex-col gap-3">
            <span className="text-xs font-bold uppercase tracking-[0.3em] text-accent">• The team behind the chat</span>
            <h2 className="max-w-2xl text-4xl leading-tight md:text-6xl">Four agents, one <span className="font-accent font-normal italic text-accent">conversation.</span></h2>
          </div>
          <p className="max-w-md text-sm leading-relaxed text-white/60">
            Built with LangGraph. Each specialist can only use its own tools, and the store&apos;s rules are checked in code underneath the model,
            so a clever prompt can&apos;t talk it into a refund it isn&apos;t allowed to give.
          </p>
        </InView>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {TEAM.map((m, i) => (
            <InView key={m.name} delay={i * 0.08}>
              <div className="glow-border flex h-full flex-col gap-5 rounded-2xl p-6" style={{ ["--glow" as string]: m.color }}>
                <div className="flex items-center gap-3">
                  <span className="size-2.5 rounded-full shadow-[0_0_16px_2px_currentColor]" style={{ background: m.color, color: m.color }} />
                  <h3 className="text-xl text-white">{m.name}</h3>
                </div>
                <p className="text-sm leading-relaxed text-white/65">{m.job}</p>
                <div className="mt-auto flex flex-wrap gap-1.5">
                  {m.tools.map((t) => (
                    <span key={t} className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 font-mono text-[0.7rem] text-white/75">{t}</span>
                  ))}
                </div>
              </div>
            </InView>
          ))}
        </div>
        <InView className="mt-8 flex justify-center">
          <button type="button" onClick={() => openChat("I'd like a refund for order O1001", true)}
            className="rounded-full border border-white/15 bg-white/[0.06] px-5 py-2.5 text-sm font-semibold text-white/90 backdrop-blur-md transition hover:bg-white/[0.12]">
            Watch them work: ask for a refund →
          </button>
        </InView>
      </section>

      <Section eyebrow="Why Brightwood" title="Made well, and looked after when it isn’t.">
        <div className="grid auto-rows-[minmax(190px,auto)] gap-4 md:grid-cols-2 lg:grid-cols-4">
          <div className="relative isolate flex flex-col justify-end overflow-hidden rounded-2xl p-6 text-white md:col-span-2 lg:row-span-2">
            <Image src={PHOTOS.lamp.src} alt="" fill sizes="(min-width: 1024px) 50vw, 100vw" className="-z-10 object-cover" />
            <div className="absolute inset-0 -z-10 bg-gradient-to-t from-black/75 via-black/30 to-black/5" aria-hidden />
            <div className="mb-6 flex max-w-sm flex-col gap-2 text-sm">
              <span className="self-end rounded-md bg-white px-3 py-2 text-[#1d1c1a]">Where is order O1003?</span>
              <span className="rounded-md bg-black/45 px-3 py-2 backdrop-blur-sm">It shipped on Tuesday and is on its way, tracking TRK1003.</span>
            </div>
            <h3 className="text-3xl text-white">Support that knows your order</h3>
            <p className="mt-2 max-w-md text-white/85">An AI team answers from your real orders and our real policies, and shows you where every answer came from.</p>
            <button type="button" onClick={() => openChat()} className="mt-4 self-start text-sm font-semibold underline underline-offset-4">Try it now</button>
          </div>
          <div className="flex flex-col justify-between rounded-2xl border border-line bg-surface p-6">
            <span className="font-display text-7xl font-semibold leading-none tracking-[-0.05em]">30</span>
            <div>
              <h3 className="text-xl">days to change your mind</h3>
              <p className="mt-1 text-sm text-muted">Free prepaid return label. Final-sale items excepted.</p>
            </div>
          </div>
          <div className="flex flex-col justify-between rounded-2xl bg-brand p-6 text-brand-ink">
            <span className="font-display text-7xl font-semibold leading-none tracking-[-0.05em]">$0</span>
            <div>
              <h3 className="text-xl">shipping over $75</h3>
              <p className="mt-1 text-sm opacity-80">Ships within one business day, arrives in 3 to 5.</p>
            </div>
          </div>
          <div className="flex flex-col justify-between gap-6 rounded-2xl border border-line bg-surface-2 p-6 md:col-span-2">
            <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
              <span className="rounded-full bg-warn-soft px-3 py-1 text-warn">Refund $189 · waiting for a manager</span>
              <span className="text-muted">→</span>
              <span className="rounded-full bg-ok-soft px-3 py-1 text-ok">Approved by support manager</span>
            </div>
            <div>
              <h3 className="text-2xl">Big decisions stay with people</h3>
              <p className="mt-1 max-w-lg text-sm text-muted">The assistant refunds up to $50 on its own. Anything larger waits for a manager, and every decision is logged.</p>
            </div>
          </div>
        </div>
      </Section>

      <Section
        id="shop"
        eyebrow="The collection"
        title="Pieces for every room"
        aside={stripe
          ? "Checkout runs in Stripe test mode: use card 4242 4242 4242 4242, any future date and any CVC. No real money moves."
          : "Payments are simulated on this server (no Stripe key set), so Buy completes instantly without a card."}
      >
        {error && <Note tone="bad">{error}</Note>}
        {products.isLoading && <p className="text-muted">Loading the collection…</p>}
        <div className="grid gap-x-6 gap-y-12 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {products.data?.map((p) => {
            const photo = PHOTOS[p.id];
            return (
              <article key={p.id} className="reveal group flex flex-col gap-3">
                <Tilt className="rounded-2xl">
                <div className="relative aspect-[4/5] overflow-hidden rounded-2xl bg-surface-2 shadow-[0_30px_60px_-30px_rgb(0_0_0/0.35)]">
                  {photo && (
                    <Image src={photo.src} alt={photo.alt} fill sizes="(min-width: 1536px) 25vw, (min-width: 1024px) 33vw, (min-width: 640px) 50vw, 100vw"
                      className="object-cover transition duration-700 group-hover:scale-[1.04]" />
                  )}
                  {p.final_sale && (
                    <span className="absolute left-3 top-3 rounded-sm bg-surface/90 px-2 py-1 text-[0.65rem] font-semibold uppercase tracking-[0.18em] text-bad">
                      Final sale
                    </span>
                  )}
                  <div className="absolute inset-x-3 bottom-3 translate-y-2 opacity-0 transition duration-300 group-focus-within:translate-y-0 group-focus-within:opacity-100 group-hover:translate-y-0 group-hover:opacity-100">
                    <Button variant="solid" className="w-full" disabled={!ready || buying !== null} onClick={() => buy(p)}>
                      {buying === p.id ? "Opening checkout…" : `Buy · ${cents(p.price_cents)}`}
                    </Button>
                  </div>
                </div>
                </Tilt>
                <div className="flex items-baseline justify-between gap-3">
                  <h3 className="text-xl">{p.name}</h3>
                  <span className="whitespace-nowrap tabular-nums">{cents(p.price_cents)}</span>
                </div>
                <p className="-mt-2 text-sm text-muted">{p.tagline} · {p.shipping_cents ? `${cents(p.shipping_cents)} shipping` : "free shipping"}</p>
                <div className="flex items-center gap-4">
                  <Button variant="solid" size="sm" className="px-5 lg:hidden" disabled={!ready || buying !== null} onClick={() => buy(p)}>
                    {buying === p.id ? "Opening…" : "Buy"}
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
      </Section>

      <Section eyebrow="Try the support team" title="Ask it anything about your orders" aside="Each card sends the question to the assistant as the customer you picked at the top.">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {TRY_ASKING.map(([q, what]) => (
            <button key={q} type="button" onClick={() => openChat(q, true)}
              className="group flex min-h-40 flex-col justify-between rounded-2xl border border-line bg-surface p-5 text-left transition duration-300 hover:-translate-y-1 hover:border-ink hover:shadow-[0_24px_50px_-28px_rgb(0_0_0/0.45)]">
              <span className="font-display text-2xl font-semibold leading-snug tracking-[-0.03em]">“{q}”</span>
              <span className="flex items-center justify-between text-sm text-muted">
                {what}<span className="transition group-hover:translate-x-1" aria-hidden>→</span>
              </span>
            </button>
          ))}
        </div>
      </Section>

      <section aria-labelledby="how-h" className="reveal flex flex-col gap-6 border-y border-line py-10">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="how-h" className="text-3xl">How this demo works</h2>
          <p className="text-sm text-muted">A pretend store with real software behind it.</p>
        </div>
        <ol className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map(([title, text], n) => (
            <li key={title} className="flex flex-col gap-1.5">
              <span className="font-display text-4xl font-semibold tracking-[-0.04em] text-muted">0{n + 1}</span>
              <h3 className="text-lg">{title}</h3>
              <p className="text-sm leading-relaxed text-muted">{text}</p>
            </li>
          ))}
        </ol>
      </section>

      <Section eyebrow="Questions" title="Good to know">
        <div className="divide-y divide-line border-y border-line">
          {FAQ.map(([q, a]) => (
            <details key={q} className="group py-5">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-6 font-display text-xl">
                {q}
                <span className="text-2xl text-muted transition group-open:rotate-45" aria-hidden>+</span>
              </summary>
              <p className="mt-3 max-w-2xl text-muted">{a}</p>
            </details>
          ))}
        </div>
      </Section>

      <footer className="grid gap-10 border-t border-line pt-10 text-sm text-muted md:grid-cols-[2fr_1fr_1fr]">
        <div className="flex flex-col gap-3">
          <span className="font-display text-xl font-bold tracking-[0.28em] text-ink">BRIGHTWOOD</span>
          <p className="max-w-md">
            A made-up store: customers and products are invented and payments are test-mode only. The support agents, their rules and
            their records are real software, built to show how an AI support team can be made safe to run.
          </p>
        </div>
        <div className="flex flex-col gap-2">
          <span className="font-semibold text-ink">Shop</span>
          <a href="#shop" className="hover:text-ink">The collection</a>
          <Link href="/orders" className="hover:text-ink">Your orders</Link>
        </div>
        <div className="flex flex-col gap-2">
          <span className="font-semibold text-ink">Help</span>
          <Link href="/help" className="hover:text-ink">Help centre</Link>
          <Link href="/how-it-works" className="hover:text-ink">How it works</Link>
        </div>
        <p className="text-xs md:col-span-3">
          Photography from <a href="https://unsplash.com" className="underline underline-offset-2" target="_blank" rel="noopener noreferrer">Unsplash</a>{" "}
          by {[HERO_PHOTO, ...Object.values(PHOTOS)].map((p) => p.credit).join(", ")}.
        </p>
      </footer>
    </div>
  );
}
