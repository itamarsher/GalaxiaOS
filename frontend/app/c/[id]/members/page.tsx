"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, type DataLabel, type Member } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

// The founder's team surface: invite humans by email with pre-set data access, see
// the roster, and set/approve each member's involvement (how they're looped in).
// The founder is always in ultimate control — a teammate can only PROPOSE their own
// involvement; the founder approves it here. All of this is founder-only server-side.
export default function MembersPage() {
  const { id } = useParams<{ id: string }>();
  const members = usePoll(() => api.members(id), 10000, [id]);
  const invites = usePoll(() => api.invites(id), 10000, [id]);
  const labels = usePoll(() => api.dataLabels(id), 0, [id]);

  const reload = () => { members.reload(); invites.reload(); };
  const labelList = labels.data ?? [];

  return (
    <div>
      <h2>Team</h2>
      <p className="muted">
        Invite people by email and choose what data they can access. They join by signing in
        with that address. Set how each teammate wants to be involved — the system routes
        decisions to them when they match, and you approve anything they propose.
      </p>

      <InviteForm companyId={id} labels={labelList} onInvited={reload} />

      {(invites.data ?? []).length > 0 && (
        <div className="card">
          <div className="step">Pending invites</div>
          {(invites.data ?? []).map((inv) => (
            <div key={inv.id} className="btnrow" style={{ justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
              <span>
                <strong>{inv.email}</strong>
                <span className="muted" style={{ fontSize: 12 }}>
                  {" "}· {inv.access_labels.length ? inv.access_labels.join(", ") : "general only"}
                </span>
              </span>
              <button className="ghost" style={{ marginTop: 0, padding: "4px 10px", fontSize: 12 }}
                onClick={async () => { await api.revokeInvite(id, inv.id); invites.reload(); }}>
                Revoke
              </button>
            </div>
          ))}
        </div>
      )}

      <h3>Members</h3>
      {members.data == null && <div className="empty">Loading…</div>}
      {(members.data ?? []).map((m) => (
        <MemberCard key={m.user_id} companyId={id} member={m} labels={labelList} onSaved={reload} />
      ))}
    </div>
  );
}

function InviteForm({ companyId, labels, onInvited }: { companyId: string; labels: DataLabel[]; onInvited: () => void }) {
  const [email, setEmail] = useState("");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);

  const toggle = (key: string) =>
    setSel((prev) => { const n = new Set(prev); if (n.has(key)) n.delete(key); else n.add(key); return n; });

  const send = async () => {
    setBusy(true); setErr(null); setSent(null);
    try {
      await api.createInvite(companyId, email.trim(), [...sel]);
      setSent(email.trim());
      setEmail(""); setSel(new Set());
      onInvited();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="step">Invite a teammate</div>
      <label>Email</label>
      <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="teammate@company.com" />
      <label style={{ marginTop: 10 }}>Data access <span className="muted" style={{ fontWeight: 400 }}>(what they can be shown)</span></label>
      {labels.length === 0 && <div className="muted" style={{ fontSize: 12 }}>No labels defined yet.</div>}
      {labels.map((l) => (
        <label key={l.key} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13, margin: "4px 0", fontWeight: 400 }}>
          <input type="checkbox" checked={sel.has(l.key)} disabled={busy} onChange={() => toggle(l.key)} />
          <span><strong>{l.name}</strong>{l.description && <span className="muted"> — {l.description}</span>}</span>
        </label>
      ))}
      <div className="btnrow" style={{ marginTop: 10, alignItems: "center" }}>
        <button style={{ marginTop: 0 }} disabled={busy || !email.trim()} onClick={send}>Send invite</button>
        {sent && <span className="muted" style={{ fontSize: 12 }}>Invited {sent}.</span>}
        {err && <span className="err">{err}</span>}
      </div>
    </div>
  );
}

function MemberCard({ companyId, member, labels, onSaved }: { companyId: string; member: Member; labels: DataLabel[]; onSaved: () => void }) {
  const isFounder = member.role === "founder";
  const [text, setText] = useState(member.involvement ?? "");
  const [sel, setSel] = useState<Set<string>>(new Set(member.access_labels));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { setText(member.involvement ?? ""); setSel(new Set(member.access_labels)); },
    [member.involvement, member.access_labels]);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setErr(null); setMsg(null);
    try { await fn(); setMsg(ok); onSaved(); }
    catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(false); }
  };

  const toggle = (key: string) =>
    setSel((prev) => { const n = new Set(prev); if (n.has(key)) n.delete(key); else n.add(key); return n; });

  return (
    <div className="card">
      <div className="btnrow" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <strong>{member.name || member.email}</strong>
        <span className="muted" style={{ fontSize: 12 }}>{member.role}{member.name ? ` · ${member.email}` : ""}</span>
      </div>

      {/* Involvement: the founder bypasses routing entirely, so it's shown for reference only. */}
      <label style={{ marginTop: 12 }}>Involvement <span className="muted" style={{ fontWeight: 400 }}>(how they&apos;re looped in)</span></label>
      <textarea value={text} onChange={(e) => setText(e.target.value)}
        placeholder={isFounder ? "You're the ultimate fallback for anything a human must own." : "e.g. Approve spend over $500; loop in on customer escalations."} />
      {member.proposed_involvement && (
        <div className="card" style={{ marginTop: 8, background: "rgba(255,200,0,0.06)" }}>
          <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Proposed by {member.name || member.email} — needs your approval</div>
          <p style={{ fontSize: 13, margin: "6px 0 0", whiteSpace: "pre-wrap" }}>{member.proposed_involvement}</p>
          <div className="btnrow" style={{ marginTop: 8 }}>
            <button style={{ marginTop: 0 }} disabled={busy}
              onClick={() => run(() => api.approveMemberInvolvement(companyId, member.user_id), "Approved.")}>
              Approve as proposed
            </button>
            <button className="ghost" style={{ marginTop: 0 }} disabled={busy}
              onClick={() => run(() => api.approveMemberInvolvement(companyId, member.user_id, text), "Approved your edit.")}>
              Approve with my edits above
            </button>
          </div>
        </div>
      )}
      <div className="btnrow" style={{ marginTop: 8, alignItems: "center" }}>
        <button style={{ marginTop: 0 }} disabled={busy || !text.trim()}
          onClick={() => run(() => api.setMemberInvolvement(companyId, member.user_id, text), "Saved.")}>
          {isFounder ? "Save my involvement" : "Set involvement"}
        </button>
      </div>

      {/* Data access — the founder bypasses segmentation, so no picker for them. */}
      {!isFounder && (
        <div style={{ marginTop: 14 }}>
          <label>Data access</label>
          {labels.length === 0 && <div className="muted" style={{ fontSize: 12 }}>No labels defined yet.</div>}
          {labels.map((l) => (
            <label key={l.key} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13, margin: "4px 0", fontWeight: 400 }}>
              <input type="checkbox" checked={sel.has(l.key)} disabled={busy} onChange={() => toggle(l.key)} />
              <span><strong>{l.name}</strong>{l.description && <span className="muted"> — {l.description}</span>}</span>
            </label>
          ))}
          <button style={{ marginTop: 8 }} disabled={busy}
            onClick={() => run(() => api.setMemberAccessLabels(companyId, member.user_id, [...sel]), "Access saved.")}>
            Save access
          </button>
        </div>
      )}
      {isFounder && <div className="muted" style={{ fontSize: 12, marginTop: 12 }}>🔓 You see all company data (the founder bypasses segmentation).</div>}

      <div style={{ marginTop: 8 }}>
        {msg && <span className="muted" style={{ fontSize: 12 }}>{msg}</span>}
        {err && <span className="err">{err}</span>}
      </div>
    </div>
  );
}
