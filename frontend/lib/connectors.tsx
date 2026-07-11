"use client";

// Shared connector cards for Cloudflare (websites & domains) and Google Drive
// (file store). They live here — rather than inline in Settings — so the same
// UI can be reused during onboarding, where they appear as optional add-ons.
//
// Both cards operate against an already-created company, so they work the moment
// a company exists (in onboarding that's right after Step 1 creates the draft).
// The Google Drive card supports a `popup` mode: instead of a full-page redirect
// (which would throw away the onboarding wizard's in-memory state), it runs the
// OAuth round-trip in a popup window and polls connection status, so onboarding
// stays exactly where it was.

import { useEffect, useRef, useState } from "react";
import { api, type ReusableCredential } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

// Reuse keys/connections saved on the founder's OTHER businesses. Credentials are
// stored per company (encrypted), so a new business would otherwise start empty and
// the founder would re-paste the same Anthropic key, re-connect Cloudflare, etc.
// This lists what's reusable and copies the selected ones into the new company in
// one click. Shown during onboarding's BYOK step; hides itself once nothing is
// left to reuse. Never shows a secret — only a fingerprint or a friendly label.
export function ReuseCredentialsCard({
  companyId,
  items,
  onReused,
}: {
  companyId: string;
  items: ReusableCredential[];
  onReused: (reusedIds: string[]) => void;
}) {
  // Everything is selected by default — the common case is "reuse it all".
  const [selected, setSelected] = useState<Set<string>>(() => new Set(items.map((i) => i.id)));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Keep the selection in step with the incoming list: preserve the founder's
  // explicit un-ticks for ids that persist, and default-select any newly-appeared
  // id. `knownIds` distinguishes "the user un-ticked this" from "brand new".
  const knownIds = useRef<Set<string>>(new Set(items.map((i) => i.id)));
  const idKey = items.map((i) => i.id).join(",");
  useEffect(() => {
    setSelected((prev) => {
      const next = new Set<string>();
      for (const it of items) {
        const isNew = !knownIds.current.has(it.id);
        if (isNew || prev.has(it.id)) next.add(it.id);
      }
      return next;
    });
    knownIds.current = new Set(items.map((i) => i.id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idKey]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const reuse = async () => {
    const ids = items.map((i) => i.id).filter((id) => selected.has(id));
    if (ids.length === 0) return;
    setBusy(true); setErr(null);
    try {
      const res = await api.reuseCredentials(companyId, ids);
      onReused(res.reused);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const chosen = items.filter((i) => selected.has(i.id)).length;

  return (
    <div className="card">
      <div className="step">Reuse from another business</div>
      <p className="muted" style={{ fontSize: 13, margin: "6px 0 10px" }}>
        You&apos;ve already set these up on another business. Reuse them here so you don&apos;t have
        to re-enter anything — or untick any you&apos;d rather leave out.
      </p>
      {items.map((it) => (
        <label
          key={it.id}
          className="kv"
          style={{ cursor: "pointer", alignItems: "center", gap: 10 }}
        >
          <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <input type="checkbox" checked={selected.has(it.id)} onChange={() => toggle(it.id)} />
            <span>
              <strong>{it.label}</strong>
              {it.detail && <span className="muted"> · <code>{it.detail}</code></span>}
              <br />
              <span className="muted" style={{ fontSize: 12 }}>
                from {it.source_company_name}
              </span>
            </span>
          </span>
          <span className={`status ${it.kind === "key" ? "active" : "pending"}`}>{it.kind}</span>
        </label>
      ))}
      <div className="btnrow">
        <button disabled={busy || chosen === 0} onClick={reuse}>
          {busy ? "Reusing…" : `Reuse ${chosen} selected`}
        </button>
      </div>
      {err && <div className="err">{err}</div>}
    </div>
  );
}

// Cloudflare powers landing-page hosting (Pages) and connecting a bought domain
// (DNS). It needs an API token (secret, encrypted at rest) plus the account id.
export function CloudflareCard({ companyId }: { companyId: string }) {
  const status = usePoll(() => api.cloudflareStatus(companyId), 0, [companyId]);
  const configured = status.data?.configured ?? false;
  const [token, setToken] = useState("");
  const [account, setAccount] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    if (token.trim().length < 8 || account.trim().length < 8) {
      setErr("Enter both the API token and the account id."); return;
    }
    setBusy(true); setErr(null);
    try {
      await api.setCloudflare(companyId, token.trim(), account.trim());
      setToken(""); setAccount("");
      status.reload();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Remove Cloudflare credentials? Landing-page hosting and domain connection will stop working.")) return;
    setBusy(true); setErr(null);
    try { await api.clearCloudflare(companyId); status.reload(); }
    catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="card">
      <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Cloudflare (websites &amp; domains)</span>
        {configured ? <span className="status active">Configured</span> : <span className="status pending">Not set</span>}
      </div>
      <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
        Lets agents publish landing pages and connect bought domains. Create an API token with
        Pages:Edit, DNS:Edit and Zone:Edit. The token is encrypted at rest; only the account id is shown back.
      </p>

      {configured && status.data?.account_id && (
        <div className="kv" style={{ marginTop: 10 }}>
          <span>Account id</span>
          <span><code>{status.data.account_id}</code></span>
        </div>
      )}

      <label>{configured ? "Replace API token" : "API token"}</label>
      <input type="password" value={token} placeholder="cfat_…"
        onChange={(e) => setToken(e.target.value)} />
      <label>Account id</label>
      <input type="text" value={account} placeholder="d543238dffd9…"
        onChange={(e) => setAccount(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && save()} />
      <div className="btnrow">
        <button disabled={busy || !token.trim() || !account.trim()} onClick={save}>
          {configured ? "Update" : "Save"}
        </button>
        {configured && <button className="ghost danger" disabled={busy} onClick={remove}>Remove</button>}
      </div>
      {err && <div className="err">{err}</div>}
    </div>
  );
}

// Google Drive is the company's file store: agents file deliverables, financial
// records, data-room docs, brand guidelines and received files into the founder's
// own Drive under .galaxia/<company>/…. One-click connect: the button sends the
// founder to Google's consent screen; the callback stores a refresh token. No
// Cloud Console setup — the deployment owns the OAuth app.
//
// `popup` mode (used in onboarding) runs the consent round-trip in a popup window
// and polls connection status instead of navigating the whole page away, so the
// onboarding wizard isn't reset mid-flow.
export function GoogleDriveCard({ companyId, popup = false }: { companyId: string; popup?: boolean }) {
  const status = usePoll(() => api.googleDriveStatus(companyId), 0, [companyId]);
  const configured = status.data?.configured ?? false;
  const canConnect = status.data?.connect_available ?? false;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Outcome of a full-page OAuth round-trip, surfaced via ?gdrive=… on return
  // (only relevant outside popup mode, i.e. in Settings). Read from the URL on
  // the client to avoid a useSearchParams suspense boundary.
  const [outcome, setOutcome] = useState<string | null>(null);
  useEffect(() => {
    if (!popup) setOutcome(new URLSearchParams(window.location.search).get("gdrive"));
  }, [popup]);

  const connect = async () => {
    setBusy(true); setErr(null);
    // Open the popup synchronously (still inside the click gesture) so popup
    // blockers don't swallow it after the await below.
    const win = popup ? window.open("", "gdrive-oauth", "width=520,height=680") : null;
    try {
      const { authorize_url } = await api.googleDriveConnect(companyId);
      if (popup) {
        if (win) win.location.href = authorize_url;
        else { window.location.href = authorize_url; return; } // popup blocked → fall back
        // Poll our own status until the callback has stored the refresh token,
        // then close the popup. We only ever read win.closed (same-origin safe);
        // the consent screen itself is cross-origin and never touched.
        const poll = window.setInterval(async () => {
          let done = false;
          try {
            const s = await api.googleDriveStatus(companyId);
            if (s.configured) done = true;
          } catch { /* keep polling */ }
          if (done || (win && win.closed)) {
            window.clearInterval(poll);
            try { win?.close(); } catch { /* ignore */ }
            status.reload();
            setBusy(false);
          }
        }, 1500);
      } else {
        window.location.href = authorize_url; // hand off to Google's consent screen
      }
    } catch (e) {
      try { win?.close(); } catch { /* ignore */ }
      setErr(String(e instanceof Error ? e.message : e));
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Disconnect Google Drive? Agents will stop filing documents to your Drive.")) return;
    setBusy(true); setErr(null);
    try { await api.clearGoogleDrive(companyId); status.reload(); }
    catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="card">
      <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Google Drive (file store)</span>
        {configured ? <span className="status active">Connected</span> : <span className="status pending">Not set</span>}
      </div>
      <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
        Your agents file every deliverable, financial record, data-room document, brand
        guideline and received file into your own Drive under <code>.galaxia/&lt;company&gt;/…</code> —
        ready for audits and due diligence. Connect with one click; GalaxiaOS only ever touches
        the files it creates.
      </p>

      {configured && status.data?.root_folder_id && (
        <div className="kv" style={{ marginTop: 10 }}>
          <span>Root folder</span>
          <span><code>{status.data.root_folder_id}</code></span>
        </div>
      )}

      {outcome === "connected" && !configured && (
        <div className="muted" style={{ fontSize: 13, marginTop: 10 }}>Connecting…</div>
      )}
      {outcome && outcome !== "connected" && (
        <div className="err">
          {outcome === "denied"
            ? "Authorization was cancelled."
            : "Couldn't connect Google Drive. Please try again."}
        </div>
      )}

      {!canConnect && !configured ? (
        <p className="muted" style={{ fontSize: 13, marginTop: 10 }}>
          Google Drive connect isn&apos;t enabled on this deployment.
        </p>
      ) : (
        <div className="btnrow">
          <button disabled={busy} onClick={connect}>
            {busy ? (popup ? "Waiting for Google…" : "Redirecting…") : configured ? "Reconnect with Google" : "Connect with Google"}
          </button>
          {configured && <button className="ghost danger" disabled={busy} onClick={remove}>Disconnect</button>}
        </div>
      )}
      {err && <div className="err">{err}</div>}
    </div>
  );
}
