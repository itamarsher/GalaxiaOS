// Minimal typed API client for the GalaxiaOS backend.

// Resolve the API base URL. NEXT_PUBLIC_* is inlined at BUILD time, so this is
// fixed when the bundle is built. Render auto-wires it from the API service's
// host (no scheme), so accept a bare host ("abos-api.onrender.com") as well as a
// full URL, and normalize to an absolute origin with no trailing slash. Falls
// back to localhost for local dev; in a production build a missing value means
// the deploy was misconfigured (every request would hit the user's own machine),
// so surface it loudly instead of failing silently with a bare login screen.
function resolveBase(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!raw) {
    if (process.env.NODE_ENV === "production") {
      // eslint-disable-next-line no-console
      console.error(
        "NEXT_PUBLIC_API_BASE_URL is not set; the app cannot reach the API. " +
          "Set it on the web service and rebuild (Clear build cache & deploy).",
      );
    }
    return "http://localhost:8000";
  }
  const withScheme = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
  return withScheme.replace(/\/+$/, "");
}

const BASE = resolveBase();

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

// ── Types ────────────────────────────────────────────────────────────────────
export interface TokenResponse { access_token: string; token_type: string }
export interface Company { id: string; name: string; status: string; mission_id: string | null; email_from: string | null }
export interface ApiKey { id: string; provider: string; key_fingerprint: string; status: string }
export interface CloudflareStatus { configured: boolean; account_id: string | null }
export interface GoogleDriveStatus { configured: boolean; root_folder_id: string | null; connect_available: boolean }
export interface ManagedStatus {
  managed_mode: boolean;
  configured: boolean;
  tier: "free" | "blocked" | "paid_managed";
  free_allowance_cents: number;
  platform_spent_cents: number;
  free_remaining_cents: number;
  spent_today_cents: number;
  daily_cap_cents: number;
  allowed: boolean;
  reason?: string | null;
  has_own_llm_key: boolean;
  byo_llm_providers: string[];
  upgrade_available: boolean;
}
export interface CompanyFile {
  id: string; category: string; name: string; description: string | null;
  mime_type: string; folder_path: string; web_url: string | null;
  size_bytes: number | null; created_at: string;
}
export interface Agent {
  id: string; role: string; name: string; autonomy_level: string;
  status: string; monthly_budget_cents: number | null; reports_to_agent_id: string | null;
  backend_type: string; source: string;
  system_prompt: string; role_description: string;
}
export interface Playbook { playbook: string; customized: boolean; default: string }
export interface AgentEdge { from_agent_id: string; to_agent_id: string; relation: string }
export interface Objective { id: string; title: string; rationale: string | null; priority: number; status: string }
export interface InvestmentReview {
  id: string; persona: string; stance: string; conviction: number;
  headline: string; thesis: string;
  strengths: string[] | null; risks: string[] | null; conditions: string[] | null;
}
export interface Preview {
  company: Company; objectives: Objective[];
  org: { agents: Agent[]; edges: AgentEdge[] }; cost_estimate_cents: number | null;
  investment_reviews: InvestmentReview[];
}
export interface BudgetView {
  budget: { limit_cents: number; spent_cents: number; reserved_cents: number };
  by_category: Record<string, number>;
  by_agent: Record<string, number>;
}
export interface Task { id: string; agent_id: string; objective_id: string | null; root_run_id: string | null; goal: string; status: string; depth: number; cost_cents: number; output: Record<string, unknown> | null }
// The game's "round" trigger + status (backend app/services/runs.py).
export interface CycleStart { started: boolean; task_id: string | null; reason: string; active: boolean }
export interface CycleStatus { active: boolean; can_start: boolean; reason: string; active_task_count: number }
export interface Decision {
  id: string; agent_id: string | null; agent_name: string | null; agent_role: string | null;
  task_id: string | null; kind: string; summary: string; status: string; created_at: string;
  task_goal: string | null; initiative: string | null; objective_title: string | null;
}
export interface TaskDetail extends Task {
  parent_task_id: string | null; created_at: string;
  agent_name: string | null; agent_role: string | null;
  input: Record<string, unknown> | null; children: Task[];
  pending_decision: Decision | null;
}
export interface TaskTranscript { task_id: string; status: string; lines: string[] }
export interface ChatTurn { who: "you" | "agent"; text: string }
// Fleet + founder collaboration (channels and founder DMs). A null agent id
// (sender/participant) is the founder.
export interface ChatParticipant { agent_id: string | null; name: string; role: string | null }
export interface ChatMessage {
  id: string; channel_id: string; thread_id: string | null; sender_agent_id: string | null;
  sender_name: string | null; sender_role: string | null; is_founder: boolean;
  body: string; created_at: string;
}
// A named sub-conversation inside a channel (a parallel sub-initiative).
export interface ChatThread {
  id: string; channel_id: string; title: string; archived: boolean; created_at: string;
  message_count: number; last_message_at: string | null;
  message_budget: number; escalation_pending: boolean;
}
export interface ChatChannel {
  id: string; name: string; purpose: string | null; kind: string; archived: boolean;
  created_at: string; participants: ChatParticipant[]; message_count: number;
  threads: ChatThread[];
  last_message_at: string | null; last_message_preview: string | null;
  waiting_agents: string[]; pending_decision: Decision | null;
}
export interface SpendEntry {
  id: string; category: string; amount_cents: number;
  vendor: string | null; sku: string | null; description: string | null;
  task_id: string | null; created_at: string;
}
export interface AgentSpend {
  agent_id: string | null; agent_name: string | null; agent_role: string | null;
  total_cents: number; entries: SpendEntry[];
}
export interface Policy { id: string; name: string; enabled: boolean; scope: string; rule: Record<string, unknown>; effect: string; priority: number }
export interface Breaker { id: string; type: string; state: string; tripped_reason: string | null }
export interface Reputation {
  agent_id: string; agent_name: string | null; agent_role: string | null;
  trust: number; accuracy: number; roi: number; reliability: number; sample_count: number;
}
export interface GenerationEvent { ts: number; label: string; pct: number }
export interface GenerationProgress {
  phase: string; pct: number; message: string;
  status: "idle" | "running" | "done" | "error"; error: string | null; events: GenerationEvent[];
}
export interface RefineResponse { reply: string; preview: Preview }
export interface ReusableCredential {
  id: string; kind: "key" | "connection"; provider: string | null;
  label: string; detail: string | null;
  source_company_id: string; source_company_name: string;
}
export interface Memory { id: string; type: string; title: string; content: string; created_at: string }
export interface Runway { projected_days_remaining: number | null; burn_rate_cents_per_day: number; balance_cents: number | null }
export interface Digest { summary_md: string | null; open_decisions: number; period_date: string | null }
export interface SiteDomain { id: string; domain: string; status: string }
export interface Site {
  id: string; slug: string; title: string; status: string;
  deployment_url: string | null; created_at: string; domains: SiteDomain[];
  lead_count: number;
}
export interface SiteLead {
  id: string; site_id: string | null; email: string;
  name: string | null; message: string | null; source: string | null; created_at: string;
}
export interface DomainQuote { domain: string; available: boolean; price_cents: number }
export interface OwnedDomain {
  id: string; domain: string; status: string;
  site_id: string | null; last_error: string | null; created_at: string;
}
export interface DomainCapabilities { registrar: string; can_buy: boolean; can_connect: boolean; can_send_email: boolean }
export interface EmailDnsRecord { record: string; type: string; name: string; ok: boolean; error: string | null }
export interface EmailSetup { domain: string; status: string; all_written: boolean; records: EmailDnsRecord[] }
export interface EmailStatus { domain: string; configured: boolean; status: string; pending: string[] }
export interface AgentListing {
  id: string; name: string; role: string; description: string; provider: string; price_cents: number;
  trust: number | null; accuracy: number | null; roi: number | null; reliability: number | null;
}
export interface ExternalMessage {
  id: string; agent_id: string | null; agent_name: string | null; agent_role: string | null;
  task_id: string | null; decision_id: string | null;
  tool: string; channel: string; recipient: string | null; subject: string | null;
  body: string | null; status: string; detail: string | null; created_at: string;
}
export interface McpServer {
  id: string; name: string; label: string; url: string; transport: string;
  enabled: boolean; has_auth: boolean; tool_count: number; tools: string[]; last_error: string | null;
}
export interface ArtifactSummary {
  id: string; kind: string; title: string;
  source_task_id: string | null; source_agent_id: string | null; created_at: string;
}
export interface Artifact extends ArtifactSummary { body_md: string }

// ── API ──────────────────────────────────────────────────────────────────────
export const api = {
  setToken(t: string) { window.localStorage.setItem("abos_token", t); },
  hasToken() { return token() != null; },
  logout() { window.localStorage.removeItem("abos_token"); },

  signup: (email: string, password: string) =>
    req<TokenResponse>("/auth/signup", { method: "POST", body: JSON.stringify({ email, password }) }),

  myCompanies: () => req<Company[]>("/companies"),

  // TEMP dev tools — remove before launch (see backend app/api/dev.py).
  devStatus: () => req<{ enabled: boolean; default_email: string | null }>("/dev/status"),
  defaultLogin: () => req<TokenResponse>("/dev/default-login", { method: "POST" }),
  deleteOtherAccounts: () =>
    req<{ deleted_accounts: number }>("/dev/delete-all-accounts", { method: "POST" }),

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
    req<ApiKey>(`/companies/${companyId}/api-keys`, {
      method: "POST",
      body: JSON.stringify({ provider, api_key: apiKey }),
    }),
  apiKeys: (companyId: string) => req<ApiKey[]>(`/companies/${companyId}/api-keys`),
  deleteApiKey: (companyId: string, keyId: string) =>
    req<void>(`/companies/${companyId}/api-keys/${keyId}`, { method: "DELETE" }),

  // Managed mode (hosted no-keys tier): the owning founder's platform standing.
  managedStatus: (companyId: string) =>
    req<ManagedStatus>(`/companies/${companyId}/managed`),
  upgradeManaged: (companyId: string) =>
    req<{ url: string }>(`/companies/${companyId}/managed/upgrade`, { method: "POST" }),

  cloudflareStatus: (companyId: string) =>
    req<CloudflareStatus>(`/companies/${companyId}/integrations/cloudflare`),
  setCloudflare: (companyId: string, apiToken: string, accountId: string) =>
    req<CloudflareStatus>(`/companies/${companyId}/integrations/cloudflare`, {
      method: "PUT",
      body: JSON.stringify({ api_token: apiToken, account_id: accountId }),
    }),
  clearCloudflare: (companyId: string) =>
    req<void>(`/companies/${companyId}/integrations/cloudflare`, { method: "DELETE" }),

  googleDriveStatus: (companyId: string) =>
    req<GoogleDriveStatus>(`/companies/${companyId}/integrations/google-drive`),
  googleDriveConnect: (companyId: string) =>
    req<{ authorize_url: string }>(
      `/companies/${companyId}/integrations/google-drive/connect`,
      { method: "POST" },
    ),
  clearGoogleDrive: (companyId: string) =>
    req<void>(`/companies/${companyId}/integrations/google-drive`, { method: "DELETE" }),

  companyFiles: (companyId: string, category?: string) =>
    req<CompanyFile[]>(
      `/companies/${companyId}/files${category ? `?category=${encodeURIComponent(category)}` : ""}`,
    ),

  // Reuse saved keys/connections from the founder's other businesses.
  reusableCredentials: (companyId: string) =>
    req<ReusableCredential[]>(`/onboarding/${companyId}/reusable-credentials`),
  reuseCredentials: (companyId: string, ids: string[]) =>
    req<{ reused: string[] }>(`/onboarding/${companyId}/reuse-credentials`, {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),

  generate: (companyId: string) => req<Preview>(`/onboarding/${companyId}/generate`, { method: "POST" }),
  generateStatus: (companyId: string) =>
    req<GenerationProgress>(`/onboarding/${companyId}/generate/status`),
  refineOnboarding: (companyId: string, message: string) =>
    req<RefineResponse>(`/onboarding/${companyId}/refine`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  preview: (companyId: string) => req<Preview>(`/onboarding/${companyId}/preview`),
  launch: (companyId: string) => req<Company>(`/onboarding/${companyId}/launch`, { method: "POST" }),

  company: (companyId: string) => req<Company>(`/companies/${companyId}`),
  updateCompany: (companyId: string, patch: { email_from?: string }) =>
    req<Company>(`/companies/${companyId}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteCompany: (companyId: string) =>
    req<void>(`/companies/${companyId}`, { method: "DELETE" }),
  resetCompany: (companyId: string) =>
    req<Company>(`/companies/${companyId}/reset`, { method: "POST" }),
  advanceCycle: (companyId: string) =>
    req<CycleStart>(`/companies/${companyId}/cycle`, { method: "POST" }),
  cycleStatus: (companyId: string) =>
    req<CycleStatus>(`/companies/${companyId}/cycle`),
  playbook: (companyId: string) => req<Playbook>(`/companies/${companyId}/playbook`),
  updatePlaybook: (companyId: string, playbook: string) =>
    req<Playbook>(`/companies/${companyId}/playbook`, {
      method: "PUT",
      body: JSON.stringify({ playbook }),
    }),

  objectives: (companyId: string) => req<Objective[]>(`/companies/${companyId}/objectives`),

  org: (companyId: string) => req<{ agents: Agent[]; edges: AgentEdge[] }>(`/companies/${companyId}/org`),
  agents: (companyId: string) => req<Agent[]>(`/companies/${companyId}/agents`),
  pauseAgent: (companyId: string, agentId: string) =>
    req<Agent>(`/companies/${companyId}/agents/${agentId}/pause`, { method: "POST" }),
  resumeAgent: (companyId: string, agentId: string) =>
    req<Agent>(`/companies/${companyId}/agents/${agentId}/resume`, { method: "POST" }),

  budget: (companyId: string) => req<BudgetView>(`/companies/${companyId}/budget`),
  budgetByAgent: (companyId: string) => req<AgentSpend[]>(`/companies/${companyId}/budget/by-agent`),
  runway: (companyId: string) => req<Runway>(`/companies/${companyId}/runway`),
  recomputeRunway: (companyId: string) =>
    req<Runway>(`/companies/${companyId}/runway/recompute`, { method: "POST" }),

  // Domains space — search availability, buy, and auto-associate to a site.
  domainCapabilities: (companyId: string) =>
    req<DomainCapabilities>(`/companies/${companyId}/domains/capabilities`),
  domainSearch: (companyId: string, q: string) =>
    req<DomainQuote[]>(`/companies/${companyId}/domains/search?q=${encodeURIComponent(q)}`),
  domains: (companyId: string) => req<OwnedDomain[]>(`/companies/${companyId}/domains`),
  buyDomain: (companyId: string, domain: string, siteId?: string) =>
    req<OwnedDomain>(`/companies/${companyId}/domains/purchase`, {
      method: "POST",
      body: JSON.stringify({ domain, site_id: siteId ?? null }),
    }),
  associateDomain: (companyId: string, domainId: string, siteId: string) =>
    req<OwnedDomain>(`/companies/${companyId}/domains/${domainId}/associate`, {
      method: "POST",
      body: JSON.stringify({ site_id: siteId }),
    }),
  setupDomainEmail: (companyId: string, domain: string) =>
    req<EmailSetup>(`/companies/${companyId}/domains/email-setup`, {
      method: "POST",
      body: JSON.stringify({ domain }),
    }),
  domainEmailStatus: (companyId: string, domain: string) =>
    req<EmailStatus>(`/companies/${companyId}/domains/email-status?domain=${encodeURIComponent(domain)}`),

  sites: (companyId: string) => req<Site[]>(`/companies/${companyId}/sites`),
  siteLeads: (companyId: string, siteId?: string) =>
    req<SiteLead[]>(
      siteId
        ? `/companies/${companyId}/sites/${siteId}/leads`
        : `/companies/${companyId}/sites/leads`,
    ),

  tasks: (companyId: string) => req<Task[]>(`/companies/${companyId}/tasks`),
  task: (companyId: string, taskId: string) =>
    req<TaskDetail>(`/companies/${companyId}/tasks/${taskId}`),
  taskTranscript: (companyId: string, taskId: string) =>
    req<TaskTranscript>(`/companies/${companyId}/tasks/${taskId}/transcript`),

  policies: (companyId: string) => req<Policy[]>(`/companies/${companyId}/policies`),
  breakers: (companyId: string) => req<Breaker[]>(`/companies/${companyId}/circuit-breakers`),
  resetBreaker: (companyId: string, breakerId: string) =>
    req<Breaker>(`/companies/${companyId}/circuit-breakers/${breakerId}/reset`, { method: "POST" }),
  reputation: (companyId: string) => req<Reputation[]>(`/companies/${companyId}/reputation`),

  // Chat — the unified collaboration surface (channels + founder DMs). Decisions
  // now show up here as founder DMs marked "waiting for a response".
  chatChannels: (companyId: string) =>
    req<ChatChannel[]>(`/companies/${companyId}/chat/channels`),
  createChatChannel: (
    companyId: string,
    body: { name: string; purpose?: string; member_roles?: string[] },
  ) =>
    req<ChatChannel>(`/companies/${companyId}/chat/channels`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  chatMessages: (companyId: string, channelId: string, threadId?: string) =>
    req<ChatMessage[]>(
      `/companies/${companyId}/chat/channels/${channelId}/messages` +
        (threadId ? `?thread_id=${threadId}` : ""),
    ),
  postChatMessage: (companyId: string, channelId: string, message: string, threadId?: string) =>
    req<ChatMessage>(`/companies/${companyId}/chat/channels/${channelId}/messages`, {
      method: "POST",
      body: JSON.stringify({ message, thread_id: threadId ?? null }),
    }),

  decisions: (companyId: string, onlyPending = true) =>
    req<Decision[]>(`/companies/${companyId}/decisions?only_pending=${onlyPending}`),
  approveDecision: (id: string, note?: string) =>
    req<Decision>(`/decisions/${id}/approve`, { method: "POST", body: JSON.stringify({ note: note ?? null }) }),
  rejectDecision: (id: string, note?: string) =>
    req<Decision>(`/decisions/${id}/reject`, { method: "POST", body: JSON.stringify({ note: note ?? null }) }),

  externalMessages: (companyId: string, status?: string) =>
    req<ExternalMessage[]>(
      `/companies/${companyId}/external-messages${status ? `?status=${status}` : ""}`
    ),
  externalApproval: (companyId: string) =>
    req<{ enabled: boolean }>(`/companies/${companyId}/settings/external-comms-approval`),
  setExternalApproval: (companyId: string, enabled: boolean) =>
    req<{ enabled: boolean }>(`/companies/${companyId}/settings/external-comms-approval`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),

  memory: (companyId: string, q?: string) =>
    req<Memory[]>(`/companies/${companyId}/memory${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  deleteMemory: (companyId: string, entryId: string) =>
    req<void>(`/companies/${companyId}/memory/${entryId}`, { method: "DELETE" }),

  digestLatest: (companyId: string) => req<Digest>(`/companies/${companyId}/digest/latest`),
  generateDigest: (companyId: string) =>
    req<Digest>(`/companies/${companyId}/digest/generate`, { method: "POST" }),
  copilotAsk: (companyId: string, question: string) =>
    req<{ answer: string; kind: string }>(`/companies/${companyId}/copilot/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  // SSE live stream. EventSource cannot set an Authorization header, so the JWT
  // is passed as a ?token= query param. Returns null if there is no token.
  eventsUrl: (companyId: string): string | null => {
    const t = token();
    if (!t) return null;
    return `${BASE}/companies/${companyId}/events?token=${encodeURIComponent(t)}`;
  },

  marketplace: () => req<AgentListing[]>(`/marketplace/listings`),
  hireAgent: (companyId: string, listingId: string) =>
    req<Agent>(`/companies/${companyId}/marketplace/hire`, {
      method: "POST",
      body: JSON.stringify({ listing_id: listingId }),
    }),

  // MCP servers — founder-pluggable tool servers.
  mcpServers: (companyId: string) => req<McpServer[]>(`/companies/${companyId}/mcp/servers`),
  addMcpServer: (
    companyId: string,
    body: { name: string; label?: string; url: string; transport?: string; auth_token?: string },
  ) =>
    req<McpServer>(`/companies/${companyId}/mcp/servers`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  refreshMcpServer: (companyId: string, serverId: string) =>
    req<McpServer>(`/companies/${companyId}/mcp/servers/${serverId}/refresh`, { method: "POST" }),
  deleteMcpServer: (companyId: string, serverId: string) =>
    req<void>(`/companies/${companyId}/mcp/servers/${serverId}`, { method: "DELETE" }),

  // Founder-facing reports (artifacts).
  reports: (companyId: string) => req<ArtifactSummary[]>(`/companies/${companyId}/reports`),
  report: (companyId: string, id: string) => req<Artifact>(`/companies/${companyId}/reports/${id}`),
  generateReport: (companyId: string, kind: string, instructions?: string) =>
    req<Artifact>(`/companies/${companyId}/reports/generate`, {
      method: "POST",
      body: JSON.stringify({ kind, instructions: instructions ?? null }),
    }),
};

export const fmtUsd = (cents: number | null | undefined) =>
  cents == null ? "—" : `$${(cents / 100).toFixed(2)}`;

/** Order tasks for the list views: tasks awaiting a founder decision first,
 *  completed (done) tasks last, everything else in between. Stable, so the
 *  backend's ordering is preserved within each group. */
export const sortTasksForView = <T extends { status: string }>(tasks: T[]): T[] => {
  const rank = (s: string) => (s === "waiting_approval" ? 0 : s === "done" ? 2 : 1);
  return [...tasks].sort((a, b) => rank(a.status) - rank(b.status));
};

/** Human-friendly label for a task/decision status (the raw value still drives CSS). */
export const statusLabel = (s: string): string =>
  s === "waiting_approval"
    ? "Needs approval"
    : s === "auditing"
      ? "CEO audit"
      : s.replace(/_/g, " ");

/** Human-friendly label for a decision kind. */
export const decisionKindLabel = (kind: string): string =>
  ({
    spend_approval: "Budget request",
    risky_action: "Risky action",
    strategy: "Strategy",
    plan_approval: "Plan approval",
    hire_approval: "Hire request",
    user_action: "Action requested",
    external_comm: "External message",
  }[kind] ?? kind.replace(/_/g, " "));
