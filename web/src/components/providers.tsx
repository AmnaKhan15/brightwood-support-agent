"use client";

import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, newSession } from "@/lib/api";
import { readStored, useStored, writeStored } from "@/lib/storage";
import type { AppState, Health, Inspect } from "@/lib/types";

type Staff = { token: string; role: string } | null;
type ChatHandler = (text: string, send: boolean) => void;
type Options = { method?: "GET" | "POST"; body?: unknown; token?: string | null };
type Api = <T>(path: string, opts?: Options) => Promise<T>;

type App = {
  ready: boolean;
  bootError: string | null;
  sid: string | null;
  customer: string;
  setCustomer: (id: string) => void;
  staff: Staff;
  setStaff: (s: Staff) => void;
  inspect: Inspect | null;
  setInspect: (i: Inspect | null) => void;
  chatOpen: boolean;
  setChatOpen: (open: boolean) => void;
  openChat: (text?: string, send?: boolean) => void;
  registerChat: (handler: ChatHandler | null) => void;
  drawerOpen: boolean;
  setDrawerOpen: (open: boolean) => void;
  api: Api;
  resetSandbox: () => Promise<void>;
  toggleTheme: () => void;
  toast: string | null;
  notify: (text: string) => void;
};

const Ctx = createContext<App | null>(null);

function AppProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [sid, setSid] = useState<string | null>(null);
  const sidRef = useRef<string | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [customerStored, setCustomerStored] = useStored("bw.customer", "C1", "session");
  const [theme, setTheme] = useStored("theme", null);
  const [staff, setStaff] = useState<Staff>(null);
  const [inspect, setInspect] = useState<Inspect | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const chatHandler = useRef<ChatHandler | null>(null);
  const customer = customerStored ?? "C1";

  const notify = useCallback((text: string) => {
    setToast(text);
    window.setTimeout(() => setToast((t) => (t === text ? null : t)), 3500);
  }, []);

  const adopt = useCallback((id: string) => {
    sidRef.current = id;
    writeStored("bw.sid", id, "session");
    setSid(id);
  }, []);

  // Keep the page's theme attribute in step with the stored choice (an external system: the DOM).
  useEffect(() => {
    if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  }, [theme]);

  // Start (or resume) this tab's sandbox.
  useEffect(() => {
    let cancelled = false;
    const existing = readStored("bw.sid", "session");
    (existing ? Promise.resolve(existing) : newSession())
      .then((id) => !cancelled && adopt(id))
      .catch((e: Error) => !cancelled && setBootError(e.message));
    return () => {
      cancelled = true;
    };
  }, [adopt]);

  const api: Api = useCallback(
    async function call<T>(path: string, opts: Options = {}, retry = true): Promise<T> {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (sidRef.current) headers["X-Session"] = sidRef.current;
      if (opts.token) headers.Authorization = `Bearer ${opts.token}`;
      const res = await fetch(path, {
        method: opts.method ?? "GET", headers, cache: "no-store",
        body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      });
      let json: { error?: string; message?: string } = {};
      try {
        json = await res.json();
      } catch {
        /* empty or non-JSON body */
      }
      if (res.status === 401 && json.error === "session_expired" && retry) {
        adopt(await newSession());
        setStaff(null);
        setInspect(null);
        notify("Your sandbox expired, so a fresh one was started.");
        void qc.invalidateQueries();
        return call<T>(path, opts, false);
      }
      if (!res.ok) throw new ApiError(json.message || `Request failed (${res.status})`, res.status, json.error || "error");
      return json as T;
    } as Api,
    [adopt, notify, qc],
  );

  const setCustomer = useCallback((id: string) => {
    setCustomerStored(id);
    setInspect(null);
  }, [setCustomerStored]);

  const registerChat = useCallback((handler: ChatHandler | null) => {
    chatHandler.current = handler;
  }, []);

  const openChat = useCallback((text?: string, send = false) => {
    setChatOpen(true);
    if (text) chatHandler.current?.(text, send);
  }, []);

  const resetSandbox = useCallback(async () => {
    await api("/api/session/reset", { method: "POST" });
    setStaff(null);
    setInspect(null);
    await qc.invalidateQueries();
    notify("Fresh orders and an empty history.");
  }, [api, qc, notify]);

  const toggleTheme = useCallback(() => {
    const dark = theme === "dark" || (theme !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    setTheme(dark ? "light" : "dark");
  }, [theme, setTheme]);

  const value = useMemo<App>(() => ({
    ready: !!sid, bootError, sid, customer, setCustomer, staff, setStaff, inspect, setInspect,
    chatOpen, setChatOpen, openChat, registerChat, drawerOpen, setDrawerOpen, api, resetSandbox,
    toggleTheme, toast, notify,
  }), [sid, bootError, customer, setCustomer, staff, inspect, chatOpen, openChat, registerChat, drawerOpen, api, resetSandbox, toggleTheme, toast, notify]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } }));
  return (
    <QueryClientProvider client={client}>
      <AppProvider>{children}</AppProvider>
    </QueryClientProvider>
  );
}

export function useApp(): App {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp must be used inside <Providers>");
  return ctx;
}

/** The sandbox state for the signed-in customer: orders, messages, approvals, audit, runs.
 *  Every change goes through a mutation that invalidates it, so a short staleTime avoids refetching on each navigation. */
export function useAppState(options: { poll?: (data: AppState | undefined) => number | false } = {}) {
  const { api, ready, sid, customer } = useApp();
  return useQuery({
    queryKey: ["state", sid, customer],
    queryFn: () => api<AppState>(`/api/state?customer=${encodeURIComponent(customer)}`),
    enabled: ready,
    staleTime: 10_000,
    refetchInterval: options.poll ? (q) => options.poll!(q.state.data) : undefined,
  });
}

export function useHealth() {
  const { api } = useApp();
  return useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/api/health"), staleTime: 15_000 });
}
