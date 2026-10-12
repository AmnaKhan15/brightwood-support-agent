"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useApp, useAppState } from "@/components/providers";
import Image from "next/image";
import { Button, Eyebrow, Note, Pill, cx } from "@/components/ui";
import { photoForItem } from "@/lib/products";

const STATUS_TONE = { delivered: "ok", cancelled: "neutral", shipped: "brand", processing: "wait" } as const;
const STAGES = ["Placed", "Shipped", "Delivered"];

/** Placed → Shipped → Delivered, filled up to the order's current stage. */
function Progress({ status }: { status: string }) {
  if (status === "cancelled") return <p className="text-sm text-muted">Cancelled before shipping · refunded in full</p>;
  const reached = { processing: 0, shipped: 1, delivered: 2 }[status] ?? 0;
  return (
    <ol className="grid grid-cols-3 gap-1.5" aria-label={`Order progress: ${STAGES[reached]}`}>
      {STAGES.map((stage, i) => (
        <li key={stage} className="flex flex-col gap-1.5">
          <span className={cx("h-1 rounded-full", i <= reached ? "bg-brand" : "bg-line")} />
          <span className={cx("text-xs", i <= reached ? "text-ink" : "text-muted")}>{stage}</span>
        </li>
      ))}
    </ol>
  );
}

export default function Orders() {
  const { api, openChat, customer, notify, ready } = useApp();
  const qc = useQueryClient();
  const { data, isLoading, error } = useAppState();
  const me = data?.customers.find((c) => c.id === customer);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  // Back from Stripe's checkout page: ask the server to confirm the payment with Stripe and create the order.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const sessionId = q.get("session_id");
    if (!ready || q.get("checkout") !== "done" || !sessionId) return;
    window.history.replaceState(null, "", "/orders");
    api<{ status: string; order_id?: string }>("/api/checkout/confirm", { method: "POST", body: { session_id: sessionId } })
      .then((r) => {
        notify(r.status === "paid" ? `Payment received. Order ${r.order_id} is confirmed.` : "The payment hasn't completed yet.");
        return qc.invalidateQueries({ queryKey: ["state"] });
      })
      .catch((e: Error) => setNote(e.message));
  }, [ready, api, notify, qc]);

  async function advance(orderId: string) {
    setBusy(orderId);
    setNote(null);
    try {
      await api(`/api/orders/${orderId}/advance`, { method: "POST", body: { customer } });
      await qc.invalidateQueries({ queryKey: ["state"] });
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (error) return <Note tone="bad">{(error as Error).message}</Note>;
  if (isLoading || !data) return <p className="text-muted">Loading your orders…</p>;

  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Eyebrow>Your account</Eyebrow>
          <h1 className="mt-1 text-3xl font-bold">Orders{me ? ` for ${me.name}` : ""}</h1>
        </div>
        <p className="max-w-md text-sm text-muted">
          The live orders table from your sandbox database. Changes made by the assistant show up here. The dashed demo buttons move an
          order along as a carrier would, so you can try returns and refunds without waiting days.
        </p>
      </div>
      {note && <Note tone="bad">{note}</Note>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.orders?.map((o) => {
          const refunds = data.refunds.filter((r) => r.order_id === o.order_id);
          return (
            <article key={o.order_id} className="flex flex-col gap-4 rounded-md border border-line bg-surface p-5">
              <h2 className="flex items-center justify-between gap-2 text-lg">
                <span className="font-mono text-base tracking-wide">Order {o.order_id}</span>
                <Pill tone={STATUS_TONE[o.status as keyof typeof STATUS_TONE] ?? "neutral"}>{o.status}</Pill>
              </h2>
              <ul className="flex flex-col gap-3">
                {o.items.map((i) => {
                  const photo = photoForItem(i.name);
                  return (
                    <li key={i.name} className="flex items-center gap-3">
                      <span className="relative size-16 shrink-0 overflow-hidden rounded-md bg-surface-2">
                        {photo && <Image src={photo.src} alt="" fill sizes="64px" className="object-cover" />}
                      </span>
                      <span className="min-w-0 flex-1 font-display text-lg leading-tight">{i.name}</span>
                      <span className="tabular-nums text-muted">{i.price}</span>
                    </li>
                  );
                })}
              </ul>
              <Progress status={o.status} />
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted">Total</dt><dd className="font-semibold">{o.total}</dd>
                <dt className="text-muted">Placed</dt><dd>{o.placed_on}</dd>
                {o.delivered_on ? (<><dt className="text-muted">Delivered</dt><dd>{o.delivered_on}</dd></>)
                  : o.shipped_on ? (<><dt className="text-muted">Last scan</dt><dd>{o.last_tracking_scan_on ?? "none"}</dd></>) : null}
                <dt className="text-muted">Refunded</dt><dd>{o.refunded}</dd>
                {refunds.map((r) => (
                  <span key={String(r.id)} className="contents">
                    <dt className="text-muted">Payment</dt>
                    <dd className="font-mono text-xs [overflow-wrap:anywhere]">
                      {r.provider === "stripe-test" ? (
                        <a className="text-brand underline" href={`https://dashboard.stripe.com/test/refunds/${encodeURIComponent(String(r.provider_refund_id))}`} target="_blank" rel="noopener noreferrer">
                          {r.provider_refund_id}
                        </a>
                      ) : r.provider_refund_id} · {r.status} · by {r.via}
                    </dd>
                  </span>
                ))}
                {o.return_label && (<><dt className="text-muted">Return label</dt><dd className="font-mono">{o.return_label.code}</dd></>)}
                {o.final_sale && (<><dt className="text-muted">Final sale</dt><dd>Yes</dd></>)}
              </dl>
              <div className="mt-auto flex flex-wrap gap-2">
                <Button size="sm" onClick={() => openChat(`Where is order ${o.order_id}?`, true)}>Track</Button>
                {o.status === "processing" && <Button size="sm" onClick={() => openChat(`Cancel order ${o.order_id}`, true)}>Cancel</Button>}
                {o.status === "delivered" && (
                  <>
                    <Button size="sm" onClick={() => openChat(`I'd like a refund for order ${o.order_id}`, true)}>Refund</Button>
                    <Button size="sm" variant="ghost" onClick={() => openChat(`Send me a return label for ${o.order_id}`, true)}>Return</Button>
                  </>
                )}
                {(o.status === "processing" || o.status === "shipped") && (
                  <Button size="sm" variant="ghost" className="border-dashed !border-line" disabled={busy !== null} onClick={() => advance(o.order_id)}
                    aria-label={`Demo control: mark ${o.order_id} as ${o.status === "processing" ? "shipped" : "delivered"}`}>
                    {busy === o.order_id ? "…" : o.status === "processing" ? "Demo: mark shipped" : "Demo: mark delivered"}
                  </Button>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
