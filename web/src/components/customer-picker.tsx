"use client";

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { cx } from "./ui";

type Customer = { id: string; name: string };

// What each demo customer is good for, so the menu doubles as a guide to the demo.
const PERSONA: Record<string, { color: string; hint: string }> = {
  C1: { color: "#d9a441", hint: "Orders delivered, shipped and processing" },
  C2: { color: "#5f9277", hint: "A $189 refund that needs a manager" },
  C3: { color: "#8a7f74", hint: "A parcel stuck in transit" },
};

function Avatar({ c, size = "size-7" }: { c: Customer; size?: string }) {
  return (
    <span className={cx("grid shrink-0 place-items-center rounded-full text-xs font-bold text-white", size)} style={{ background: PERSONA[c.id]?.color ?? "var(--accent)" }} aria-hidden>
      {c.name.charAt(0)}
    </span>
  );
}

/** "You are" switcher in the site's style: a pill that opens a small menu of demo customers.
 *  Keyboard: arrows move, Enter or Space picks, Esc closes. */
export function CustomerPicker({ customers, value, onChange }: { customers: Customer[]; value: string; onChange: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const id = useId();
  const current = customers.find((c) => c.id === value) ?? customers[0];

  // Close when clicking anywhere else.
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => !root.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener("pointerdown", away);
    return () => window.removeEventListener("pointerdown", away);
  }, [open]);

  const show = () => {
    setActive(Math.max(0, customers.findIndex((c) => c.id === value)));
    setOpen(true);
    requestAnimationFrame(() => list.current?.focus());
  };
  const pick = (c: Customer) => {
    onChange(c.id);
    setOpen(false);
    root.current?.querySelector("button")?.focus();
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown") setActive((i) => (i + 1) % customers.length);
    else if (e.key === "ArrowUp") setActive((i) => (i - 1 + customers.length) % customers.length);
    else if (e.key === "Enter" || e.key === " ") pick(customers[active]);
    else if (e.key === "Escape") {
      setOpen(false);
      root.current?.querySelector("button")?.focus();
    } else return;
    e.preventDefault();
  };

  if (!current) return null;
  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={id}
        aria-label={`You are ${current.name}. Change demo customer`}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={(e) => (e.key === "ArrowDown" || e.key === "ArrowUp") && (e.preventDefault(), show())}
        className="flex items-center gap-2 rounded-full border border-line bg-surface py-1 pl-1 pr-3 text-sm font-semibold transition hover:border-ink"
      >
        <Avatar c={current} />
        <span className="hidden sm:inline">{current.name}</span>
        <span className="sm:hidden">{current.name.split(" ")[0]}</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden
          className={cx("text-muted transition", open && "rotate-180")}>
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      <AnimatePresence>
        {open && (
          <motion.ul
            ref={list}
            id={id}
            role="listbox"
            tabIndex={-1}
            aria-label="Demo customers"
            aria-activedescendant={`${id}-${customers[active]?.id}`}
            onKeyDown={onKey}
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.18 }}
            className="absolute right-0 top-[calc(100%+0.5rem)] z-50 w-72 origin-top-right rounded-3xl border border-line bg-bg p-2 shadow-[0_24px_60px_-24px_rgb(22_21_20/0.45)] outline-none"
          >
            <li role="presentation" className="px-3 pb-2 pt-1.5 text-[0.65rem] font-bold uppercase tracking-[0.26em] text-accent">• Shop as</li>
            {customers.map((c, i) => {
              const selected = c.id === value;
              return (
                <li
                  key={c.id}
                  id={`${id}-${c.id}`}
                  role="option"
                  aria-selected={selected}
                  onPointerEnter={() => setActive(i)}
                  onClick={() => pick(c)}
                  className={cx("flex cursor-pointer items-center gap-3 rounded-2xl px-3 py-2.5 transition-colors", i === active && "bg-surface-2")}
                >
                  <Avatar c={c} size="size-9" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold">{c.name}</span>
                    <span className="block truncate text-xs text-muted">{PERSONA[c.id]?.hint ?? "Demo customer"}</span>
                  </span>
                  {selected && (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden className="text-accent">
                      <path d="M20 6 9 17l-5-5" />
                    </svg>
                  )}
                </li>
              );
            })}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}
