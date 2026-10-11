"use client";

import { useApp } from "./providers";
import { Note } from "./ui";

export function Toast() {
  const { toast, bootError } = useApp();
  if (bootError) {
    return (
      <div className="fixed inset-x-4 top-20 z-50 mx-auto max-w-lg">
        <Note tone="bad">The site could not start: {bootError}</Note>
      </div>
    );
  }
  if (!toast) return null;
  return (
    <div role="status" className="fixed bottom-24 left-1/2 z-50 -translate-x-1/2 rounded-md bg-ink px-4 py-2.5 text-sm font-semibold text-bg shadow-card">
      {toast}
    </div>
  );
}
