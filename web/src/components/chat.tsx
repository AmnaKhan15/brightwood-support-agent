"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { CHIPS } from "@/lib/products";
import { useStored } from "@/lib/storage";
import type { ChatResponse, Message } from "@/lib/types";
import { speak, useVoice } from "@/lib/voice";
import { useApp, useAppState } from "./providers";
import { Button, Pill, StatePill, cx } from "./ui";

const MONEY = /\b(refund|cancel|money back|reimburse)\b/i;
const YES = /^(yes|yeah|yep|confirm|go ahead|do it|sure|please do)\b/i;
const NO = /^(no|nope|cancel that|stop|never mind)\b/i;

type Bubble = { role: Message["role"]; text: string; id?: number };

// The assistant cites help passages as [article#section], e.g. [refunds#refund-limits-for-the-assistant].
// Customers see a readable source label instead of the raw id.
function sourceLabel(id: string) {
  const section = id.split("#")[1] ?? id;
  const words = section.replace(/-/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function withCitations(text: string) {
  return text.split(/([[a-z_]+#[a-z0-9-]+])/g).map((part, i) =>
    /^[[a-z_]+#[a-z0-9-]+]$/.test(part) ? (
      <span key={i} title={`From the help article: ${part.slice(1, -1).split("#")[0].replace(/_/g, " ")}`}
        className="mx-0.5 inline-flex items-center gap-1 whitespace-nowrap rounded-md bg-brand-soft px-1.5 text-[0.72rem] font-semibold text-brand">
        Source: {sourceLabel(part.slice(1, -1))}
      </span>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

export function Chat() {
  const path = usePathname();
  const qc = useQueryClient();
  const { api, ready, sid, customer, chatOpen, setChatOpen, registerChat, inspect, setInspect, setDrawerOpen } = useApp();
  const { data } = useAppState();
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  // Bubbles not yet saved on the server (the message being sent, a voice read-back). They belong to one
  // sandbox and customer, so switching either one shows none.
  const scope = `${sid}:${customer}`;
  const [pending, setPending] = useState<{ scope: string; items: Bubble[] }>({ scope, items: [] });
  const extra = pending.scope === scope ? pending.items : [];
  const setExtra = useCallback((items: Bubble[]) => setPending({ scope, items }), [scope]);
  const [voiceStored, setVoiceStored] = useStored("voice", "0");
  const voiceOut = voiceStored === "1";
  const confirm = useRef<string | null>(null);
  const log = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLInputElement>(null);

  const me = data?.customers.find((c) => c.id === customer);
  const stored: Bubble[] = (data?.messages ?? []).map((m) => ({ role: m.role, text: m.text, id: m.id }));
  const bubbles: Bubble[] = [...stored, ...extra];
  // The inspector belongs to the assistant message the last run stored.
  const inspectedId = inspect?.stored.find((s) => s.table === "messages" && s.role === "assistant")?.id;

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight });
  }, [bubbles.length, busy, chatOpen]);

  const send = useCallback(
    async (raw: string, spoken = false) => {
      const text = raw.trim();
      if (!text || busy || !ready) return;
      setBusy(true);
      setInput("");
      setExtra([{ role: "customer", text }]);
      try {
        const r = await api<ChatResponse>("/api/chat", { method: "POST", body: { customer, message: text, voice: spoken || voiceOut } });
        setInspect(r.inspect);
        await qc.invalidateQueries({ queryKey: ["state"] });
        setExtra([]);
        if (spoken || voiceOut) speak(r.reply);
      } catch (e) {
        await qc.invalidateQueries({ queryKey: ["state"] });
        setExtra([{ role: "customer", text }, { role: "system", text: (e as Error).message }]);
      } finally {
        setBusy(false);
        field.current?.focus();
      }
    },
    [api, busy, customer, qc, ready, setInspect, voiceOut, setExtra],
  );

  // Spoken money actions get a read-back and a spoken "yes" before anything is sent.
  const onSpoken = useCallback(
    (text: string) => {
      if (confirm.current) {
        const pending = confirm.current;
        confirm.current = null;
        if (YES.test(text)) return void send(pending, true);
        if (NO.test(text)) {
          const m = "Okay, I won't do that.";
          setExtra([{ role: "customer", text }, { role: "assistant", text: m }]);
          speak(m);
          setInput("");
          return;
        }
      }
      if (MONEY.test(text)) {
        confirm.current = text;
        const m = `Just to check: you said "${text}". Say yes to go ahead, or no to stop.`;
        setExtra([{ role: "customer", text }, { role: "assistant", text: m }]);
        speak(m);
        setInput("");
        return;
      }
      void send(text, true);
    },
    [send, setExtra],
  );
  const voice = useVoice(onSpoken, setInput);

  // Other parts of the page (product cards, order buttons) open the chat with a message.
  useEffect(() => {
    registerChat((text, sendNow) => {
      if (sendNow) void send(text);
      else {
        setInput(text);
        field.current?.focus();
      }
    });
    return () => registerChat(null);
  }, [registerChat, send]);

  if (path.startsWith("/staff")) return null;

  if (!chatOpen) {
    return (
      <button
        type="button"
        onClick={() => setChatOpen(true)}
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full bg-brand px-5 py-3 font-semibold text-brand-ink shadow-card hover:opacity-90"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-5.4A8 8 0 1 1 21 12z" />
        </svg>
        Ask support
      </button>
    );
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void send(input);
  };

  return (
    <section
      aria-label="Support chat"
      className="fixed inset-x-2 bottom-2 z-40 flex max-h-[85vh] flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-card sm:inset-x-auto sm:right-5 sm:bottom-5 sm:h-[640px] sm:w-[400px]"
    >
      <div className="flex flex-col gap-2 border-b border-line px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand" aria-hidden>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="4" y="7" width="16" height="12" rx="4" /><path d="M12 7V4M9 13h.01M15 13h.01" /></svg>
          </div>
          <div className="min-w-0 flex-1">
            <b className="block truncate">Brightwood support</b>
            <small className="block truncate text-muted">{me?.name ?? "…"} · AI assistant</small>
          </div>
          <Button size="sm" variant="ghost" aria-label="Close chat" onClick={() => { window.speechSynthesis?.cancel(); setChatOpen(false); }}>✕</Button>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" aria-pressed={voiceOut} title="Read answers aloud"
            onClick={() => { setVoiceStored(voiceOut ? "0" : "1"); if (voiceOut) window.speechSynthesis?.cancel(); }}>
            Voice: {voiceOut ? "on" : "off"}
          </Button>
          <Button size="sm" variant="outline" onClick={() => setDrawerOpen(true)}>Behind the scenes</Button>
        </div>
      </div>

      <div ref={log} className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-4" aria-live="polite">
        {!bubbles.length && (
          <div className="max-w-[85%] rounded-2xl rounded-tl-sm bg-surface-2 px-3.5 py-2.5 text-sm">
            Hi {me?.name.split(" ")[0] ?? ""}, I&apos;m Brightwood&apos;s support assistant. I can look up your orders, cancel or return them, answer from our help articles, and pass anything bigger to a person.
          </div>
        )}
        {bubbles.map((b, i) => {
          const isLast = !extra.length && b.id !== undefined && b.id === inspectedId;
          return (
            <div
              key={i}
              className={cx(
                "max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm",
                b.role === "customer" && "self-end rounded-tr-sm bg-brand text-brand-ink",
                b.role === "assistant" && "rounded-tl-sm bg-surface-2",
                b.role === "system" && "self-center bg-warn-soft text-center text-xs",
              )}
            >
              {b.role === "assistant" ? withCitations(b.text) : b.text}
              {isLast && inspect && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <StatePill state={inspect.state} />
                  {inspect.agent && <Pill tone="brand">{inspect.agent} agent</Pill>}
                  {inspect.provider && <Pill>{inspect.provider}</Pill>}
                  <button type="button" className="text-xs font-semibold text-brand underline" onClick={() => setDrawerOpen(true)}>See what happened</button>
                </div>
              )}
            </div>
          );
        })}
        {busy && <div className="typing self-start rounded-2xl bg-surface-2 px-3 py-2.5" aria-label="Assistant is typing"><i /><i /><i /></div>}
      </div>

      <div className="flex gap-1.5 overflow-x-auto px-3 pb-2 [scrollbar-width:none]">
        {(CHIPS[customer] ?? []).map(([t, warn]) => (
          <button
            key={t}
            type="button"
            onClick={() => void send(t)}
            disabled={busy}
            className={cx("whitespace-nowrap rounded-full border px-3 py-1 text-xs font-semibold", warn ? "border-bad/40 text-bad" : "border-line text-muted hover:text-ink")}
          >
            {t}
          </button>
        ))}
      </div>
      {voice.note && <div className="px-4 pb-2 text-xs text-muted">{voice.note}</div>}
      <form onSubmit={submit} className="flex items-center gap-2 border-t border-line p-3">
        <Button
          variant={voice.listening ? "solid" : "outline"}
          size="sm"
          aria-label="Speak your message"
          aria-pressed={voice.listening}
          disabled={!voice.supported}
          title={voice.supported ? "Speak your message" : "This browser has no speech recognition. Try Chrome, Edge or Safari."}
          onClick={() => (voice.listening ? voice.stop() : voice.start())}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
        </Button>
        <input
          ref={field}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={500}
          autoComplete="off"
          placeholder="Ask about an order, a return or a refund"
          aria-label="Message"
          className="min-w-0 flex-1 rounded-xl border border-line bg-bg px-3 py-2 text-sm"
        />
        <Button type="submit" variant="solid" size="sm" disabled={busy || !input.trim()}>Send</Button>
      </form>
    </section>
  );
}
