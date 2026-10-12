/** The three specialists the supervisor routes to, with how each one orbits in the 3D scene.
 *  Kept apart from the scene so pages can use the list without loading three.js. */
export type AgentId = "policy" | "orders" | "billing";

export const AGENTS: { id: AgentId; label: string; color: string; radius: number; speed: number; tilt: number; phase: number }[] = [
  { id: "policy", label: "Policy", color: "#5eead4", radius: 2.25, speed: 0.24, tilt: 0.42, phase: 0.4 },
  { id: "orders", label: "Orders", color: "#fbbf24", radius: 2.75, speed: 0.18, tilt: -0.3, phase: 2.5 },
  { id: "billing", label: "Billing", color: "#c4b5fd", radius: 3.2, speed: 0.14, tilt: 0.16, phase: 4.6 },
];
