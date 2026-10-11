"use client";

// Voice in and out with the browser's own speech APIs: no extra service, no cost.
// Chrome may send the audio to Google to transcribe it; the chat says so the first time.

import { useCallback, useRef, useState } from "react";
import { useBrowserCheck } from "./storage";

type Recognition = {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
};

function recognitionClass(): (new () => Recognition) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

function bestVoice(): SpeechSynthesisVoice | null {
  const voices = (window.speechSynthesis?.getVoices() || []).filter((v) => /^en/i.test(v.lang));
  const rank = (v: SpeechSynthesisVoice) =>
    (/natural|neural|online/i.test(v.name) ? 3 : 0) + (/google|samantha|aria|jenny|ava|zira|daniel/i.test(v.name) ? 2 : 0) + (v.localService ? 0 : 1);
  return voices.sort((a, b) => rank(b) - rank(a))[0] || null;
}

export function speak(text: string) {
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const clean = text.replace(/\[[a-z_]+#[a-z0-9-]+\]/g, "").replace(/\bO(\d{4})\b/g, "O $1").replace(/\s+/g, " ").trim();
  const u = new SpeechSynthesisUtterance(clean);
  const v = bestVoice();
  if (v) u.voice = v;
  u.rate = 1.02;
  u.lang = v?.lang || "en-US";
  window.speechSynthesis.speak(u);
}

export function useVoice(onFinal: (text: string) => void, onInterim: (text: string) => void) {
  const supported = useBrowserCheck(() => !!recognitionClass());
  const [listening, setListening] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const rec = useRef<Recognition | null>(null);
  const noted = useRef(false);

  const start = useCallback(() => {
    const Rec = recognitionClass();
    if (!Rec || listening) return;
    window.speechSynthesis?.cancel();
    const r = new Rec();
    r.lang = "en-US";
    r.interimResults = true;
    r.maxAlternatives = 1;
    rec.current = r;
    let finalText = "";
    setListening(true);
    setNote(noted.current ? "Listening" : "Listening. Your browser turns speech into text, and Chrome may send the audio to Google to do it. Card numbers are hidden before the assistant sees them.");
    noted.current = true;
    r.onresult = (e) => {
      let t = "";
      for (const res of Array.from(e.results)) {
        t += res[0].transcript;
        if (res.isFinal) finalText = t;
      }
      onInterim(t);
    };
    r.onerror = (e) => {
      setListening(false);
      setNote(e.error === "not-allowed" ? "Microphone access was blocked. Allow it in the address bar, or type instead."
        : e.error === "no-speech" ? "I didn't hear anything. Press the microphone and try again." : `Speech recognition stopped: ${e.error}`);
    };
    r.onend = () => {
      setListening(false);
      if (finalText.trim()) {
        setNote(null);
        onFinal(finalText.trim());
      }
    };
    try {
      r.start();
    } catch {
      setListening(false);
    }
  }, [listening, onFinal, onInterim]);

  const stop = useCallback(() => rec.current?.stop(), []);
  return { supported, listening, note, start, stop };
}
