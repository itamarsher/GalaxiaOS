"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, type ExternalMessage } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

// External-message statuses reuse the shared `.status.*` badge styles; a couple
// map onto an existing class with the right colour.
const STATUS_CLASS: Record<string, string> = {
  sent: "done",
  pending_approval: "waiting_approval",
  failed: "failed",
  blocked: "blocked",
  rejected: "rejected",
};

const STATUS_LABEL: Record<string, string> = {
  sent: "Sent",
  pending_approval: "Awaiting approval",
  failed: "Failed",
  blocked: "Blocked",
  rejected: "Rejected",
};

export default function CommunicationsPage() {
  const { id } = useParams<{ id: string }>();
  const messages = usePoll(() => api.externalMessages(id), 5000, [id]);
  const list = messages.data ?? [];

  return (
    <div>
      <h2>Communications</h2>
      <p className="muted">
        Every message the fleet sends outside the company — emails, posts, published pages,
        ads, notifications — indexed as it happens.
      </p>

      <ApprovalToggle companyId={id} />

      <div className="card">
        <div className="step">Outbound message log</div>
        <table>
          <thead>
            <tr><th>When</th><th>Channel</th><th>To / Subject</th><th>Agent</th><th>Status</th></tr>
          </thead>
          <tbody>
            {list.map((m) => <MessageRow key={m.id} m={m} companyId={id} />)}
          </tbody>
        </table>
        {list.length === 0 && <p className="muted">No external messages yet.</p>}
      </div>
    </div>
  );
}

function ApprovalToggle({ companyId }: { companyId: string }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    api.externalApproval(companyId)
      .then((r) => { if (active) setEnabled(r.enabled); })
      .catch(() => { if (active) setEnabled(false); });
    return () => { active = false; };
  }, [companyId]);

  const toggle = async () => {
    if (enabled === null) return;
    setBusy(true);
    try {
      const r = await api.setExternalApproval(companyId, !enabled);
      setEnabled(r.enabled);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <div>
          <div className="step" style={{ marginBottom: 4 }}>Approve every external message</div>
          <span className="muted" style={{ fontSize: 13 }}>
            When on, every outbound communication pauses for your sign-off in the{" "}
            <Link href={`/c/${companyId}/decisions`}>Decisions</Link> inbox, where you can
            discuss it with the agent before it goes out. Useful for early cycles.
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flex: "0 0 auto" }}>
          <span className={`status ${enabled ? "active" : ""}`}>
            {enabled === null ? "…" : enabled ? "On" : "Off"}
          </span>
          <button disabled={busy || enabled === null} onClick={toggle} style={{ marginTop: 0 }}>
            {enabled ? "Turn off" : "Turn on"}
          </button>
        </div>
      </div>
    </div>
  );
}

function MessageRow({ m, companyId }: { m: ExternalMessage; companyId: string }) {
  const [open, setOpen] = useState(false);
  const headline = m.subject || m.recipient || m.channel;
  return (
    <>
      <tr onClick={() => setOpen((o) => !o)} style={{ cursor: "pointer" }}>
        <td className="muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
          {new Date(m.created_at).toLocaleString()}
        </td>
        <td><span className="pill">{m.channel}</span></td>
        <td>
          {m.recipient && <div style={{ fontSize: 13 }}>{m.recipient}</div>}
          {m.subject && <div className="muted" style={{ fontSize: 12 }}>{m.subject}</div>}
          {!m.recipient && !m.subject && <span className="muted">{headline}</span>}
        </td>
        <td className="muted" style={{ fontSize: 12 }}>
          {m.agent_name ?? "—"}{m.agent_role ? ` · ${m.agent_role}` : ""}
        </td>
        <td>
          <span className={`status ${STATUS_CLASS[m.status] ?? ""}`}>
            {STATUS_LABEL[m.status] ?? m.status}
          </span>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={5} style={{ background: "color-mix(in srgb, var(--muted) 6%, transparent)" }}>
            {m.body && <div style={{ whiteSpace: "pre-wrap", fontSize: 13, marginBottom: 6 }}>{m.body}</div>}
            {m.detail && <div className="muted" style={{ fontSize: 12 }}>{m.detail}</div>}
            {m.status === "pending_approval" && m.decision_id && (
              <Link href={`/c/${companyId}/decisions`}>Review in Decisions →</Link>
            )}
            {!m.body && !m.detail && <span className="muted">No content recorded.</span>}
          </td>
        </tr>
      )}
    </>
  );
}
