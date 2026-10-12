"use client";

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { readStored, writeStored } from "@/lib/storage";
import { speak, voicesReady } from "@/lib/voice";
import { useApp } from "./providers";
import { cx } from "./ui";

const GREETING =
  "Hi, welcome to Brightwood! I'm your support assistant. I can track your orders, handle returns and refunds, " +
  "and answer questions about our policies. Just tap Ask support, and type or talk to me any time.";

// Character offset where each word starts, so the word being spoken can be highlighted.
const WORDS = GREETING.split(" ").reduce<{ word: string; at: number }[]>((list, word) => {
  const prev = list[list.length - 1];
  list.push({ word, at: prev ? prev.at + prev.word.length + 1 : 0 });
  return list;
}, []);

type Phase = "hidden" | "waiting" | "speaking" | "done";

/** A spoken welcome from the support assistant, once per visit.
 *  Browsers only allow sound after the visitor has interacted with the page, so until then the card
 *  invites a tap, and the first click or key press anywhere starts the voice. */
export function VoiceGreeting() {
  const { openChat, chatOpen } = useApp();
  const [phase, setPhase] = useState<Phase>("hidden");
  const [spoken, setSpoken] = useState(-1); // index of the word being said
  const [canSpeak, setCanSpeak] = useState(true);
  const dismissed = useRef(false); // closed while the voice was still loading: stay quiet

  const say = useCallback(async () => {
    await voicesReady();
    if (dismissed.current) return;
    setSpoken(-1);
    const ok = speak(GREETING, {
      onStart: () => !dismissed.current && setPhase("speaking"),
      onWord: (at) => setSpoken(WORDS.findLastIndex((w) => w.at <= at)),
      onEnd: () => {
        // Closing the card cancels the speech, which also ends it: don't bring the card back.
        if (dismissed.current) return;
        setPhase("done");
        setSpoken(WORDS.length);
      },
    });
    if (!ok) {
      setCanSpeak(false);
      setPhase("done");
      setSpoken(WORDS.length);
    }
  }, []);
  const sayRef = useRef(say);

  // Appear shortly after the page loads, once per browser tab.
  useEffect(() => {
    if (readStored("bw.greeted", "session")) return;
    const timer = window.setTimeout(() => {
      writeStored("bw.greeted", "1", "session");
      const allowed = (navigator as Navigator & { userActivation?: { hasBeenActive: boolean } }).userActivation?.hasBeenActive;
      setPhase("waiting");
      if (allowed) void sayRef.current();
    }, 1200);
    return () => window.clearTimeout(timer);
  }, []);

  // Still waiting for permission to make sound: the first click or key press anywhere starts the greeting.
  useEffect(() => {
    if (phase !== "waiting") return;
    const start = () => void sayRef.current();
    window.addEventListener("pointerdown", start, { once: true });
    window.addEventListener("keydown", start, { once: true });
    return () => {
      window.removeEventListener("pointerdown", start);
      window.removeEventListener("keydown", start);
    };
  }, [phase]);

  const close = () => {
    dismissed.current = true;
    window.speechSynthesis?.cancel();
    setPhase("hidden");
  };
  const talk = () => {
    dismissed.current = true;
    window.speechSynthesis?.cancel();
    setPhase("hidden");
    openChat();
  };

  const visible = phase !== "hidden" && !chatOpen;
  const speaking = phase === "speaking";

  return (
    <AnimatePresence>
      {visible && (
        <motion.aside
          role="status"
          aria-label="Voice greeting from the support assistant"
          initial={{ opacity: 0, y: 24, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 16, scale: 0.97 }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
          className="fixed bottom-[5.25rem] right-5 z-40 max-h-[calc(100dvh-7rem)] w-[min(340px,calc(100vw-2.5rem))] overflow-y-auto rounded-[26px] border border-line bg-bg p-5 shadow-[0_30px_70px_-28px_rgb(22_21_20/0.5)]"
        >
          <div className="flex items-center gap-3">
            <div className="relative grid size-11 shrink-0 place-items-center rounded-full bg-ink text-lg font-extrabold text-bg" aria-hidden>
              B
              {speaking && <span className="absolute inset-0 animate-ping rounded-full bg-accent/40" />}
              <span className="absolute bottom-0 right-0 size-3 rounded-full bg-ok ring-[3px] ring-bg" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[0.65rem] font-bold uppercase tracking-[0.26em] text-accent">• Voice assistant</p>
              <p className="flex items-center gap-2 text-sm font-semibold">
                {speaking ? "Speaking" : phase === "waiting" ? "Tap anywhere to hear me" : canSpeak ? "Here to help" : "Voice isn't available in this browser"}
                <span className={cx("sound-bars", speaking && "is-speaking")} aria-hidden><i /><i /><i /><i /></span>
              </p>
            </div>
            <button type="button" aria-label="Close the greeting" onClick={close}
              className="grid size-8 shrink-0 place-items-center rounded-full border border-line text-muted transition hover:bg-ink hover:text-bg">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" aria-hidden><path d="M18 6 6 18M6 6l12 12" /></svg>
            </button>
          </div>

          {/* The words light up as they are spoken. */}
          <p className="mt-4 text-[0.95rem] leading-relaxed">
            {WORDS.map((w, i) => (
              <span key={i} className={cx("transition-colors duration-200", phase === "waiting" ? "text-muted" : i <= spoken ? "text-ink" : "text-muted/50", i === spoken && "text-accent")}>
                {w.word}{" "}
              </span>
            ))}
          </p>

          <div className="mt-4 flex items-center gap-2">
            <button type="button" onClick={talk}
              className="inline-flex items-center gap-2 rounded-full bg-ink px-4 py-2.5 text-sm font-semibold text-bg transition hover:bg-accent">
              Talk to me
            </button>
            {canSpeak && (
              <button type="button" onClick={() => phase !== "waiting" && void say()} disabled={speaking}
                className="inline-flex items-center gap-2 rounded-full border border-line px-4 py-2.5 text-sm font-semibold transition hover:border-ink disabled:opacity-50">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="M11 5 6 9H2v6h4l5 4zM15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14" />
                </svg>
                {phase === "waiting" ? "Play" : "Replay"}
              </button>
            )}
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
