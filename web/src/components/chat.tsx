"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { CHIPS } from "@/lib/products";
import { useStored } from "@/lib/storage";
import type { ChatResponse, Message } from "@/lib/types";
import { speakAnswer, stopSpeaking, useVoice, type VoiceState } from "@/lib/voice";
import { useApp, useAppState } from "./providers";
import { AGENTS } from "./three/agents";
import { Pill, StatePill, cx } from "./ui";

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

const CITATION = /^\[[a-z_]+#[a-z0-9-]+\]$/;
const INLINE = /(\[[a-z_]+#[a-z0-9-]+\]|\*\*[^*\n]+\*\*|`[^`\n]+`)/g;
const BULLET = /^\s*(?:[*-]|\d+\.)\s+/;

/** Bold, inline code and help citations inside one line of an answer. */
function inline(text: string) {
  return text.split(INLINE).map((part, i) => {
    if (CITATION.test(part)) {
      const id = part.slice(1, -1);
      return (
        <span key={i} title={`From the help article: ${id.split("#")[0].replace(/_/g, " ")}`}
          className="mx-0.5 inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-accent-soft px-2 text-[0.72rem] font-semibold text-accent">
          Source: {sourceLabel(id)}
        </span>
      );
    }
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={i} className="rounded bg-surface-2 px-1 font-mono text-[0.8em]">{part.slice(1, -1)}</code>;
    return <span key={i}>{part}</span>;
  });
}

/** The model answers in light markdown: paragraphs, bullet lists, **bold** and `code`. Render that, not the symbols. */
function formatAnswer(text: string) {
  const blocks: React.ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (!list.length) return;
    blocks.push(
      <ul key={blocks.length} className="flex list-disc flex-col gap-1 pl-5 marker:text-accent">
        {list.map((item, i) => <li key={i}>{inline(item)}</li>)}
      </ul>,
    );
    list = [];
  };
  for (const line of text.split("\n")) {
    if (BULLET.test(line)) list.push(line.replace(BULLET, ""));
    else {
      flush();
      if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line)}</p>);
    }
  }
  flush();
  return <div className="flex flex-col gap-2">{blocks}</div>;
}

export function Chat() {
  const path = usePathname();
  const qc = useQueryClient();
  const { api, ready, sid, customer, chatOpen, setChatOpen, registerChat, inspect, setInspect, setDrawerOpen } = useApp();
  const { data } = useAppState();
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
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
        if (spoken || voiceOut) void speakAnswer(r.reply, setVoiceState);
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
          void speakAnswer(m, setVoiceState);
          setInput("");
          return;
        }
      }
      if (MONEY.test(text)) {
        confirm.current = text;
        const m = `Just to check: you said "${text}". Say yes to go ahead, or no to stop.`;
        setExtra([{ role: "customer", text }, { role: "assistant", text: m }]);
        void speakAnswer(m, setVoiceState);
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
        className="group fixed bottom-5 right-5 z-40 flex items-center gap-2.5 rounded-full bg-ink py-3 pl-3.5 pr-5 text-sm font-semibold text-bg shadow-[0_18px_40px_-14px_rgb(22_21_20/0.6)] transition hover:-translate-y-0.5 hover:bg-accent"
      >
        <span className="relative grid size-7 place-items-center rounded-full bg-bg/15">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-5.4A8 8 0 1 1 21 12z" />
          </svg>
          <span className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full bg-accent ring-2 ring-ink transition group-hover:bg-bg group-hover:ring-accent" />
        </span>
        Ask support
      </button>
    );
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void send(input);
  };
  const first = me?.name.split(" ")[0];

  return (
    <section
      aria-label="Support chat"
      className="fixed inset-x-2 bottom-2 z-40 flex max-h-[85vh] flex-col overflow-hidden rounded-[28px] border border-line bg-bg shadow-[0_40px_80px_-30px_rgb(22_21_20/0.45)] sm:inset-x-auto sm:right-5 sm:bottom-5 sm:h-[680px] sm:w-[430px]"
    >
      {/* Header in the site's own voice: wordmark, orange tag line, quiet controls. */}
      <div className="flex flex-col gap-4 border-b border-line px-5 pb-4 pt-5">
        <div className="flex items-start gap-3">
          <div className="relative grid size-11 shrink-0 place-items-center rounded-full bg-ink text-lg font-extrabold text-bg" aria-hidden>
            B<span className="absolute bottom-0 right-0 size-3 rounded-full bg-ok ring-[3px] ring-bg" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[0.65rem] font-bold uppercase tracking-[0.26em] text-accent">• Support · online</p>
            <b className="block truncate text-xl font-extrabold tracking-[-0.03em]">
              Brightwood<span className="text-accent">.</span>{" "}
              <span className="font-accent text-[1.35rem] font-normal italic tracking-normal text-muted">support</span>
            </b>
          </div>
          <button type="button" aria-label="Close chat" className="grid size-9 shrink-0 place-items-center rounded-full border border-line transition hover:bg-ink hover:text-bg"
            onClick={() => { stopSpeaking(); setVoiceState("idle"); setChatOpen(false); }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden><path d="M18 6 6 18M6 6l12 12" /></svg>
          </button>
        </div>
        <div className="flex items-center gap-2 text-xs font-semibold">
          <button type="button" aria-pressed={voiceOut} title="Read answers aloud"
            className={cx("rounded-full border px-3 py-1.5 transition", voiceOut ? "border-ink bg-ink text-bg" : "border-line text-muted hover:border-ink hover:text-ink")}
            onClick={() => { setVoiceStored(voiceOut ? "0" : "1"); if (voiceOut) { stopSpeaking(); setVoiceState("idle"); } }}>
            Voice {voiceOut ? "on" : "off"}
          </button>
          <button type="button" className="rounded-full border border-line px-3 py-1.5 text-muted transition hover:border-ink hover:text-ink" onClick={() => setDrawerOpen(true)}>
            Behind the scenes ↗
          </button>
          <span className="ml-auto truncate text-muted">Helping {first ?? "you"}</span>
        </div>
      </div>

      <div ref={log} data-lenis-prevent className="flex flex-1 flex-col gap-3 overflow-y-auto px-5 py-5" aria-live="polite">
        {!bubbles.length && (
          <div className="flex flex-col gap-3">
            <h3 className="text-2xl leading-tight">
              Hi{first ? ` ${first}` : ""}, <span className="font-accent font-normal italic text-accent">how can we help?</span>
            </h3>
            <p className="max-w-[90%] text-sm leading-relaxed text-muted">
              I can look up your orders, cancel or return them, answer from our help articles, and pass anything bigger to a person.
            </p>
          </div>
        )}
        {bubbles.map((b, i) => {
          const isLast = !extra.length && b.id !== undefined && b.id === inspectedId;
          const agent = isLast ? AGENTS.find((a) => a.id === inspect?.agent) : undefined;
          return (
            <div
              key={i}
              className={cx(
                "max-w-[85%] px-4 py-3 text-sm leading-relaxed",
                b.role === "customer" && "self-end whitespace-pre-wrap rounded-[20px] rounded-br-md bg-ink text-bg",
                b.role === "assistant" && "rounded-[20px] rounded-bl-md border border-line bg-surface",
                b.role === "system" && "self-center rounded-full bg-warn-soft px-3 py-1.5 text-center text-xs",
              )}
            >
              {b.role === "assistant" ? formatAnswer(b.text) : b.text}
              {isLast && inspect && (
                <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-line pt-2.5">
                  <StatePill state={inspect.state} />
                  {inspect.agent && (
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-bg px-2.5 py-0.5 text-xs font-semibold">
                      <span className="size-2 rounded-full" style={{ background: agent?.color ?? "var(--accent)" }} />
                      {inspect.agent.charAt(0).toUpperCase() + inspect.agent.slice(1)} agent
                    </span>
                  )}
                  {inspect.provider && <Pill>{inspect.provider.startsWith("gemini") ? "Gemini" : inspect.provider.startsWith("offline") ? "Backup assistant" : inspect.provider}</Pill>}
                  <button type="button" className="link-underline ml-auto text-xs font-semibold text-accent" onClick={() => setDrawerOpen(true)}>See what happened</button>
                </div>
              )}
            </div>
          );
        })}
        {busy && <div className="typing self-start rounded-[20px] rounded-bl-md border border-line bg-surface px-4 py-3" aria-label="Assistant is typing"><i /><i /><i /></div>}
      </div>

      <div className="flex gap-1.5 overflow-x-auto px-4 pb-3 [scrollbar-width:none]">
        {(CHIPS[customer] ?? []).map(([t, warn]) => (
          <button
            key={t}
            type="button"
            onClick={() => void send(t)}
            disabled={busy}
            className={cx("whitespace-nowrap rounded-full border px-3.5 py-1.5 text-xs font-semibold transition disabled:opacity-50",
              warn ? "border-accent/40 text-accent hover:bg-accent hover:text-white" : "border-line bg-surface text-muted hover:border-ink hover:text-ink")}
          >
            {t}
          </button>
        ))}
      </div>
      {voiceState !== "idle" && (
        <div className="mx-4 mb-2 flex items-center gap-2 rounded-full border border-line bg-surface px-3.5 py-1.5 text-xs font-semibold text-muted" role="status">
          <span className={cx("sound-bars", voiceState === "speaking" && "is-speaking")} aria-hidden><i /><i /><i /><i /></span>
          {voiceState === "preparing" ? "Preparing voice…" : "Speaking"}
          <button type="button" className="link-underline ml-auto text-ink" onClick={() => { stopSpeaking(); setVoiceState("idle"); }}>Stop</button>
        </div>
      )}
      {voice.note && <div className="px-5 pb-2 text-xs text-muted">{voice.note}</div>}
      <form onSubmit={submit} className="px-4 pb-4">
        <div className="flex items-center gap-1.5 rounded-full border border-line bg-surface p-1.5 pl-2 transition focus-within:border-ink">
          <button
            type="button"
            aria-label="Speak your message"
            aria-pressed={voice.listening}
            disabled={!voice.supported}
            title={voice.supported ? "Speak your message" : "This browser has no speech recognition. Try Chrome, Edge or Safari."}
            onClick={() => (voice.listening ? voice.stop() : voice.start())}
            className={cx("grid size-9 shrink-0 place-items-center rounded-full transition disabled:opacity-40", voice.listening ? "bg-accent text-white" : "text-muted hover:bg-surface-2 hover:text-ink")}
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
          </button>
          <input
            ref={field}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            maxLength={500}
            autoComplete="off"
            placeholder="Ask about an order, a return or a refund"
            aria-label="Message"
            className="min-w-0 flex-1 bg-transparent px-1 py-2 text-sm outline-none placeholder:text-muted/80 focus-visible:outline-none"
          />
          <button type="submit" aria-label="Send" disabled={busy || !input.trim()}
            className="grid size-9 shrink-0 place-items-center rounded-full bg-accent text-white transition hover:bg-ink disabled:bg-line disabled:text-muted">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M7 17 17 7M8 7h9v9" /></svg>
          </button>
        </div>
      </form>
    </section>
  );
}
