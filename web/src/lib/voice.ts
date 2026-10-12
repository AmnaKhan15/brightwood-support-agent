"use client";

// Voice in and out with the browser's own speech APIs: no extra service, no cost.
// Chrome may send the audio to Google to transcribe it; the chat says so the first time.

import { useCallback, useRef, useState } from "react";
import { readStored, useBrowserCheck } from "./storage";

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

type SpeakEvents = { onStart?: () => void; onEnd?: () => void; onWord?: (charIndex: number) => void };

const CITATION = /\[[a-z_]+#[a-z0-9-]+\]/g;
const BULLET = /^\s*(?:[*-]|\d+\.)\s+/gm;
const CODE = /\b([A-Z]{1,4})(\d{3,})\b/g;

/** The answer as a person would say it: no markdown or citation ids, codes like TRK1003 spelled out.
 *  Mirrors spoken_text() in the API's speech module. */
export function spokenText(text: string) {
  const lines = text.replace(CITATION, "").replace(/\*\*|`|#/g, "").replace(BULLET, "").split("\n").map((l) => l.trim()).filter(Boolean);
  return lines
    .map((l) => (/[.!?:]$/.test(l) ? l : `${l}.`))
    .join(" ")
    .replace(CODE, (_, letters: string, digits: string) => `${letters.split("").join(" ")} ${digits.split("").join(" ")}`)
    .replace(/\s+/g, " ")
    .replace(/\s+([.,!?:;])/g, "$1")
    .trim();
}

/** Reads text aloud with the best English voice the browser has. Returns false when it has none.
 *  Speaks one sentence at a time: Chrome stops long utterances part-way through. */
export function speak(text: string, events: SpeakEvents = {}) {
  if (typeof window === "undefined" || !window.speechSynthesis) return false;
  window.speechSynthesis.cancel();
  const clean = spokenText(text);
  const sentences = clean.match(/[^.!?]+[.!?]*/g) ?? [clean];
  const v = bestVoice();
  let offset = 0;
  sentences.forEach((sentence, i) => {
    const start = clean.indexOf(sentence, offset);
    offset = start + sentence.length;
    const u = new SpeechSynthesisUtterance(sentence);
    if (v) u.voice = v;
    u.rate = 1.02;
    u.lang = v?.lang || "en-US";
    if (i === 0) u.onstart = () => events.onStart?.();
    if (i === sentences.length - 1) u.onend = () => events.onEnd?.();
    u.onerror = (e) => e.error !== "interrupted" && e.error !== "canceled" && events.onEnd?.();
    u.onboundary = (e) => e.name === "word" && events.onWord?.(start + e.charIndex);
    window.speechSynthesis.speak(u);
  });
  return true;
}

// The answer currently being played in the natural voice, so a new one (or Stop) can cut it off.
let player: HTMLAudioElement | null = null;
let turn = 0;

/** Stops whatever is being said, natural voice or browser voice. */
export function stopSpeaking() {
  turn++;
  player?.pause();
  player = null;
  if (typeof window !== "undefined") window.speechSynthesis?.cancel();
}

/** Reads an answer in the natural Gemini voice from /api/tts; falls back to the browser's voice if that is unavailable. */
export async function speakAnswer(text: string) {
  stopSpeaking();
  const mine = turn;
  // The current sandbox, read now: it may have been renewed while the answer was being written.
  const session = readStored("bw.sid", "session");
  try {
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(session ? { "X-Session": session } : {}) },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error(`tts ${res.status}`);
    const url = URL.createObjectURL(await res.blob());
    if (mine !== turn) return URL.revokeObjectURL(url); // something newer started meanwhile
    const audio = new Audio(url);
    audio.onended = () => URL.revokeObjectURL(url);
    player = audio;
    await audio.play();
  } catch {
    if (mine === turn) speak(text);
  }
}

/** Voices load asynchronously in some browsers; wait briefly so the first sentence uses a good one. */
export function voicesReady(timeout = 1200): Promise<void> {
  const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
  if (!synth || synth.getVoices().length) return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      synth.removeEventListener("voiceschanged", done);
      resolve();
    };
    synth.addEventListener("voiceschanged", done);
    window.setTimeout(done, timeout);
  });
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
    stopSpeaking();
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
