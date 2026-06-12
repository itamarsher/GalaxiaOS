// Minimal typed API client for the ABOS backend.

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

function token(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("abos_token");
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  const t = token();
  if (t) headers["Authorization"] = `Bearer ${t}`;

  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export interface TokenResponse { access_token: string; token_type: string }
export interface Company { id: string; name: string; status: string; mission_id: string | null }
export interface Agent {
  id: string; role: string; name: string; autonomy_level: string;
  status: string; monthly_budget_cents: number | null; reports_to_agent_id: string | null;
  backend_type: string; source: string;
}
export interface AgentEdge { from_agent_id: string; to_agent_id: string; relation: string }
export interface Objective { id: string; title: string; rationale: string | null; priority: number; status: string }
export interface Preview {
  company: Company; objectives: Objective[];
  org: { agents: Agent[]; edges: AgentEdge[] }; cost_estimate_cents: number | null;
}

export const api = {
  setToken(t: string) { window.localStorage.setItem("abos_token", t); },

  signup: (email: string, password: string) =>
    req<TokenResponse>("/auth/signup", { method: "POST", body: JSON.stringify({ email, password }) }),

  login: async (email: string, password: string) => {
    const form = new URLSearchParams({ username: email, password });
    const res = await fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(),
    });
    if (!res.ok) throw new Error(await res.text());
    return (await res.json()) as TokenResponse;
  },

  startOnboarding: (mission_text: string, budget_cents: number, constraints: string[]) =>
    req<Company>("/onboarding/start", {
      method: "POST",
      body: JSON.stringify({ mission_text, budget_cents, constraints }),
    }),

  addApiKey: (companyId: string, apiKey: string, provider = "anthropic") =>
    req<unknown>(`/companies/${companyId}/api-keys`, {
      method: "POST",
      body: JSON.stringify({ provider, api_key: apiKey }),
    }),

  generate: (companyId: string) =>
    req<Preview>(`/onboarding/${companyId}/generate`, { method: "POST" }),

  preview: (companyId: string) => req<Preview>(`/onboarding/${companyId}/preview`),

  launch: (companyId: string) =>
    req<Company>(`/onboarding/${companyId}/launch`, { method: "POST" }),

  org: (companyId: string) =>
    req<{ agents: Agent[]; edges: AgentEdge[] }>(`/companies/${companyId}/org`),

  budget: (companyId: string) =>
    req<{ budget: { limit_cents: number; spent_cents: number; reserved_cents: number };
          by_category: Record<string, number>; by_agent: Record<string, number> }>(
      `/companies/${companyId}/budget`,
    ),

  tasks: (companyId: string) =>
    req<Array<{ id: string; goal: string; status: string; depth: number; cost_cents: number }>>(
      `/companies/${companyId}/tasks`,
    ),
};
