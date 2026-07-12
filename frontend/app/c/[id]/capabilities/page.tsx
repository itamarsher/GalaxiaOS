"use client";

import { useParams } from "next/navigation";
import { api, type FeatureRequest } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

// The founder's view of the request→delivery loop: every capability (or bug) the
// company's agents and founders asked the platform for, who asked, and how far
// along it is — open (accruing demand), promoted (filed as a tracker issue), or
// delivered (shipped, and the requesting agents told to resume).
const STATUS_LABEL: Record<string, string> = {
  open: "Requested",
  promoted: "In progress",
  delivered: "Delivered",
};

function requesterLabel(r: FeatureRequest["requesters"][number]): string {
  if (r.agent_name) return r.agent_name;
  if (r.user_email) return r.user_email;
  return "Someone";
}

export default function CapabilitiesPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error } = usePoll(() => api.featureRequests(id), 15000, [id]);
  const items = data ?? [];
  const delivered = items.filter((f) => f.status === "delivered").length;

  return (
    <div>
      <h2>Capabilities</h2>
      <p className="muted">
        What your fleet has asked the platform for, and what it has delivered. When an agent
        hits a gap it files a request here; once the platform marks it ready, the agents that
        asked are told to resume the work that was blocked.
      </p>
      {error && <div className="empty">Could not load capabilities.</div>}
      {data && items.length === 0 && (
        <div className="empty">No capability requests yet — your agents haven&apos;t hit a gap.</div>
      )}
      {items.length > 0 && (
        <p className="muted" style={{ fontSize: 12 }}>
          {items.length} requested · {delivered} delivered
        </p>
      )}
      {items.map((f) => (
        <div key={f.id} className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span className="pill">{f.kind}</span>
              <span className={`pill ${f.status === "delivered" ? "" : "muted"}`}>
                {STATUS_LABEL[f.status] ?? f.status}
              </span>
            </div>
            <span className="muted" style={{ fontSize: 12 }}>
              {f.vote_count} request{f.vote_count === 1 ? "" : "s"}
            </span>
          </div>
          <strong style={{ display: "block", margin: "8px 0 4px" }}>{f.title}</strong>
          <span className="muted">{f.details}</span>
          <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            Requested by: {f.requesters.map(requesterLabel).join(", ") || "—"}
          </div>
          {f.github_issue_url && (
            <div style={{ fontSize: 12, marginTop: 4 }}>
              <a href={f.github_issue_url} target="_blank" rel="noreferrer">
                Tracking issue #{f.github_issue_number}
              </a>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
