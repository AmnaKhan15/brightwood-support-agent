"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useApp, useAppState } from "./providers";
import { Button, Pill, cx } from "./ui";

const NAV = [
  ["/", "Shop"],
  ["/orders", "Your orders"],
  ["/help", "Help centre"],
  ["/how-it-works", "How it works"],
  ["/staff", "Staff"],
] as const;

export function Header() {
  const path = usePathname();
  const { customer, setCustomer, resetSandbox, toggleTheme, ready } = useApp();
  const { data } = useAppState();
  const staffMode = path.startsWith("/staff");

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <Link href="/" className="flex items-center gap-2 font-display text-lg font-bold">
          <span className="inline-block size-6 rounded-lg bg-brand" aria-hidden />
          Brightwood
          {staffMode && <Pill tone="brand">staff</Pill>}
        </Link>
        <nav aria-label="Main" className="order-3 flex w-full gap-1 overflow-x-auto sm:order-none sm:w-auto">
          {NAV.map(([href, label]) => {
            const active = href === "/" ? path === "/" : path.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-semibold", active ? "bg-brand-soft text-brand" : "text-muted hover:text-ink")}
              >
                {label}
                {href === "/staff" && !!data?.pending && <Pill tone="wait" className="ml-1.5">{data.pending}</Pill>}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-muted">
            <span className="hidden md:inline">Signed in as</span>
            <select
              aria-label="Signed-in customer"
              value={customer}
              onChange={(e) => setCustomer(e.target.value)}
              className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm font-semibold text-ink"
            >
              {(data?.customers ?? [{ id: "C1", name: "Sam Rivera" }]).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </label>
          <Button size="sm" variant="ghost" onClick={() => resetSandbox()} disabled={!ready} title="Start over with fresh orders">Reset</Button>
          <Button size="sm" variant="ghost" onClick={toggleTheme} aria-label="Switch light and dark theme">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
            </svg>
          </Button>
        </div>
      </div>
    </header>
  );
}
