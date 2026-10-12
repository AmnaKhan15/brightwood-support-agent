"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useApp, useAppState } from "./providers";
import { Button, Pill, cx } from "./ui";

// Pages a customer sees. The staff console has its own mode, chosen with the Customer / Staff switch.
const CUSTOMER_NAV = [
  ["/", "Shop"],
  ["/orders", "Your orders"],
  ["/help", "Help centre"],
  ["/how-it-works", "How it works"],
] as const;

export function Header() {
  const path = usePathname();
  const router = useRouter();
  const { customer, setCustomer, resetSandbox, toggleTheme, ready, staff } = useApp();
  const { data } = useAppState();
  const staffMode = path.startsWith("/staff");
  const pending = data?.pending ?? 0;

  return (
    <header className="sticky top-0 z-30 border-b border-line/60 bg-bg/70 backdrop-blur-xl backdrop-saturate-150">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6 lg:px-10">
        <Link href="/" className="font-display text-lg font-bold tracking-[0.18em] text-ink sm:text-xl sm:tracking-[0.28em]" aria-label="Brightwood, home">
          BRIGHTWOOD
        </Link>

        {!staffMode && (
          <nav aria-label="Main" className="order-3 flex w-full gap-1 overflow-x-auto md:order-none md:w-auto">
            {CUSTOMER_NAV.map(([href, label]) => {
              const active = href === "/" ? path === "/" : path.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cx("whitespace-nowrap px-3 py-1.5 text-sm underline-offset-[10px] decoration-1", active ? "text-ink underline" : "text-muted hover:text-ink")}
                >
                  {label}
                </Link>
              );
            })}
          </nav>
        )}

        <div className="ml-auto flex items-center gap-2">
          {staffMode ? (
            staff ? <Pill tone="ok">signed in as {staff.role.replace("_", " ")}</Pill> : <Pill>not signed in</Pill>
          ) : (
            <label className="flex items-center gap-2 text-sm text-muted">
              <span className="hidden lg:inline">You are</span>
              <select
                aria-label="Which demo customer you are"
                value={customer}
                onChange={(e) => setCustomer(e.target.value)}
                className="rounded-md border border-line bg-surface px-2 py-1.5 text-sm font-semibold text-ink"
              >
                {(data?.customers ?? [{ id: "C1", name: "Sam Rivera" }]).map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </label>
          )}
          <div role="group" aria-label="View the app as" className="flex rounded-full border border-line bg-surface p-0.5">
            <button
              type="button"
              aria-pressed={!staffMode}
              onClick={() => staffMode && router.push("/")}
              className={cx("rounded-full px-3.5 py-1.5 text-sm font-semibold transition", !staffMode ? "bg-brand text-brand-ink" : "text-muted hover:text-ink")}
            >
              Customer
            </button>
            <button
              type="button"
              aria-pressed={staffMode}
              onClick={() => !staffMode && router.push("/staff")}
              className={cx("flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-semibold transition", staffMode ? "bg-brand text-brand-ink" : "text-muted hover:text-ink")}
            >
              Staff
              {pending > 0 && <span className="rounded-full bg-warn px-1.5 text-xs font-bold text-white" aria-label={`${pending} refunds waiting`}>{pending}</span>}
            </button>
          </div>
          <Button size="sm" variant="ghost" onClick={() => resetSandbox()} disabled={!ready} title="Start over: fresh demo orders, an empty chat and no approvals" aria-label="Reset demo">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden className="lg:hidden"><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></svg>
            <span className="hidden lg:inline">Reset demo</span>
          </Button>
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
