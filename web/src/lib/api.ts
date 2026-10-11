// Helpers for the Python API. The request function itself lives in components/providers.tsx (useApp().api).

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
  ) {
    super(message);
  }
}

export async function newSession(): Promise<string> {
  const res = await fetch("/api/session", { method: "POST", cache: "no-store" });
  if (!res.ok) throw new ApiError("Could not start a sandbox. Is the API running?", res.status, "session");
  return ((await res.json()) as { session: string }).session;
}

export const usd = (n: number | string, digits = 2) => `${Number(n).toFixed(digits)}`;
export const cents = (n: number | string) => usd(Number(n) / 100);
export const pct = (n: number | null | undefined) => (n == null ? "–" : `${Math.round(n * 1000) / 10}%`);
