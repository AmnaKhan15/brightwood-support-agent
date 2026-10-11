"use client";

// Small values the browser remembers (theme, chosen customer, voice switch), read with
// useSyncExternalStore so the server render and the first client render agree, and so every
// component that reads a key updates when it changes. Storage can be blocked (private mode),
// so every access is wrapped and falls back to the default.

import { useCallback, useSyncExternalStore } from "react";

type Area = "local" | "session";
const EVENT = "bw-storage";

function area(which: Area): Storage | null {
  try {
    return which === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function readStored(key: string, which: Area = "local"): string | null {
  try {
    return area(which)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string | null, which: Area = "local") {
  try {
    const s = area(which);
    if (value === null) s?.removeItem(key);
    else s?.setItem(key, value);
  } catch {
    /* blocked: the value just is not remembered */
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: key }));
}

function subscribe(onChange: () => void) {
  window.addEventListener("storage", onChange);
  window.addEventListener(EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(EVENT, onChange);
  };
}

export function useStored(key: string, fallback: string | null, which: Area = "local"): [string | null, (v: string | null) => void] {
  const value = useSyncExternalStore(subscribe, () => readStored(key, which) ?? fallback, () => fallback);
  const set = useCallback((v: string | null) => writeStored(key, v, which), [key, which]);
  return [value, set];
}

const noop = () => () => {};
/** True in a browser that has the given capability; false on the server. */
export function useBrowserCheck(check: () => boolean): boolean {
  return useSyncExternalStore(noop, check, () => false);
}
