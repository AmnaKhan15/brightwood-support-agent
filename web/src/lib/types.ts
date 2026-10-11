// Shapes returned by the Python API (see src/brightwood_support/service.py). OpenAPI docs: /api/docs.

export type Customer = { id: string; name: string };

export type OrderItem = { name: string; price: string };
export type Order = {
  order_id: string;
  status: "processing" | "shipped" | "delivered" | "cancelled" | string;
  placed_on: string;
  shipped_on: string | null;
  delivered_on: string | null;
  last_tracking_scan_on: string | null;
  tracking: string | null;
  items: OrderItem[];
  total: string;
  shipping_paid: string;
  final_sale: boolean;
  address: string;
  refunded: string;
  return_label: { code: string; expires_on: string } | null;
};

export type Message = { id: number; role: "customer" | "assistant" | "system"; text: string; created_at: string };

export type Approval = {
  id: number;
  customer: string;
  order_id: string;
  amount: number;
  reason: string;
  needs: string;
  status: "pending" | "processing" | "approved" | "rejected" | string;
  decided_by: string | null;
};

export type Row = Record<string, string | number | null>;

export type Span = { name: string; attrs: Record<string, unknown>; duration_s: number };

export type GatewayReport = {
  providers: Record<string, { calls: number; failures: number; skipped_open: number; avg_seconds: number }>;
  cache_hits: number;
  fallbacks: number;
  degraded: number;
};

export type Step = { kind: "ok" | "wait" | "no" | ""; title: string; detail: string; data?: string; status?: string };

export type Inspect = {
  run_id: number;
  customer: string;
  state: "ok" | "waiting" | "blocked" | "refused" | "stopped";
  stopped: string;
  provider: string | null;
  route: string | null;
  agent: string | null;
  route_reason: string | null;
  millis: number;
  tokens: number;
  typed: string;
  masked: string;
  stored: { table: string; id: number; role?: string }[];
  retrieved: { id: string; score: number; text: string }[];
  steps: Step[];
  prompt: { role: string; text: string }[];
  tools: Span[];
  summary: { model_calls: number; tool_calls: number; tokens: number; cost: number | null };
  gateway: GatewayReport;
  retrieval: string;
};

export type AppState = {
  customers: Customer[];
  approvals: Approval[];
  tickets: Row[];
  refunds: Row[];
  audit: Row[];
  runs: Row[];
  pending: number;
  orders?: Order[];
  messages?: Message[];
  inspect?: Inspect | null;
};

export type ChatResponse = { reply: string; state: Inspect["state"]; inspect: Inspect; pending: number };

export type Health = {
  ok: boolean;
  version: string;
  uptime_s: number;
  mode: string;
  agents: string;
  database: string;
  redis: boolean;
  jobs: string;
  payments: string;
  retrieval: string;
  help_chunks: number;
  staff_login: "demo" | "access-code" | "off";
  sessions: number;
  ai_calls_today: number;
  ai_daily_cap: number;
  gateway: GatewayReport;
};

export type Target = { metric: string; target: string; value: number | null; met: boolean | null; meaning: string };
export type Metrics = {
  window_days: number;
  conversations: number;
  containment_rate: number | null;
  escalation_rate: number | null;
  approval_rate: number | null;
  failure_rate: number | null;
  rule_blocks: number;
  injection_flags: number;
  fallback_rate: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  avg_tokens: number | null;
  cost_per_conversation_usd: number | null;
  approvals_decided: number;
  approvals_approved: number;
  median_approval_wait_s: number | null;
  by_agent: Record<string, number>;
  targets: Target[];
};

export type SearchHit = { id: string; heading: string; text: string; score: number };
export type Article = { doc: string; chunks: { id: string; heading: string; text: string }[] };
