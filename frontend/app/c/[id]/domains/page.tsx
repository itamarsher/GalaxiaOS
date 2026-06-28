"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { api, fmtUsd, type DomainQuote, type EmailSetup, type OwnedDomain } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

// SiteConnectStatus → a short, human label. "live" is the happy end state.
const statusLabel = (s: string) =>
  ({ pending_ns: "needs nameservers", ns_set: "nameservers set", zone_active: "DNS active",
     attaching: "connecting", live: "live", failed: "failed" }[s] ?? s.replace(/_/g, " "));

export default function DomainsPage() {
  const { id } = useParams<{ id: string }>();
  const caps = usePoll(() => api.domainCapabilities(id), 0, [id]);
  const owned = usePoll(() => api.domains(id), 6000, [id]);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<DomainQuote[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [buying, setBuying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [emailBusy, setEmailBusy] = useState<string | null>(null);
  const [emailResult, setEmailResult] = useState<Record<string, EmailSetup>>({});

  const setupEmail = async (domain: string) => {
    setEmailBusy(domain);
    setError(null);
    try {
      const res = await api.setupDomainEmail(id, domain);
      setEmailResult((m) => ({ ...m, [domain]: res }));
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setEmailBusy(null);
    }
  };

  const canBuy = caps.data?.can_buy ?? false;

  const runSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setError(null);
    try {
      setResults(await api.domainSearch(id, query.trim()));
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setResults(null);
    } finally {
      setSearching(false);
    }
  };

  const buy = async (domain: string) => {
    setBuying(domain);
    setError(null);
    try {
      await api.buyDomain(id, domain); // buys + auto-associates to the latest site
      setResults((rs) => rs?.filter((r) => r.domain !== domain) ?? null);
      owned.reload();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBuying(null);
    }
  };

  return (
    <div>
      <h2>Domains</h2>
      <p className="muted" style={{ marginTop: -6 }}>
        Search a name, click once to buy it, and it’s connected to your site automatically.
      </p>

      {caps.data && !canBuy && (
        <div className="card" style={{ borderColor: "var(--warn, #b08900)" }}>
          <div className="step">Set up purchasing</div>
          <p className="muted">
            No domain registrar is connected yet (currently <span className="pill">{caps.data.registrar}</span>).
            Configure one (<code>ABOS_DOMAIN_REGISTRAR</code>) to buy domains from here.
          </p>
        </div>
      )}
      {caps.data && canBuy && !caps.data.can_connect && (
        <p className="muted">
          You can buy domains; to auto-connect them, publish a site and connect Cloudflare in Settings.
          Until then, bought domains are saved here and connect once those are in place.
        </p>
      )}

      <div className="card">
        <div className="step">Find a domain</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runSearch()}
            placeholder="your-startup  (or your-startup.com)"
            style={{ flex: 1 }}
            disabled={!canBuy}
          />
          <button onClick={runSearch} disabled={!canBuy || searching || !query.trim()}>
            {searching ? "Searching…" : "Search"}
          </button>
        </div>

        {results && results.length === 0 && <p className="muted" style={{ marginTop: 10 }}>No matches.</p>}
        {results?.map((r) => (
          <div key={r.domain} className="line" style={{ marginTop: 10 }}>
            <span style={{ minWidth: 0 }}>
              <strong>{r.domain}</strong>
              <span className="pill" style={{ marginLeft: 8 }}>
                {r.available ? fmtUsd(r.price_cents) : "taken"}
              </span>
            </span>
            <button
              onClick={() => buy(r.domain)}
              disabled={!r.available || buying != null}
              style={{ flex: "0 0 auto" }}
            >
              {buying === r.domain ? "Buying…" : "Buy & connect"}
            </button>
          </div>
        ))}
      </div>

      {error && (
        <div className="card" style={{ borderColor: "var(--danger, #c0392b)" }}>
          <p style={{ margin: 0 }}>{error}</p>
        </div>
      )}

      <div className="card">
        <div className="step">Your domains</div>
        {owned.data && owned.data.length > 0 ? (
          owned.data.map((d: OwnedDomain) => {
            const em = emailResult[d.domain];
            return (
              <div key={d.id} style={{ borderBottom: "1px solid var(--line, #eee)", padding: "6px 0" }}>
                <div className="kv" style={{ border: 0, padding: 0 }}>
                  <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {d.domain}
                    {d.last_error && (
                      <span className="muted" style={{ fontSize: 11, display: "block" }}>{d.last_error}</span>
                    )}
                  </span>
                  <span style={{ display: "flex", alignItems: "center", gap: 8, flex: "0 0 auto" }}>
                    <button
                      className="navbtn"
                      style={{ fontSize: 12, padding: "2px 8px" }}
                      onClick={() => setupEmail(d.domain)}
                      disabled={emailBusy != null}
                      title="Register this domain with Resend and write its email DNS into Cloudflare"
                    >
                      {emailBusy === d.domain ? "Setting up…" : "Set up email"}
                    </button>
                    <span className={`pill${d.status === "live" ? " live" : ""}`}>{statusLabel(d.status)}</span>
                  </span>
                </div>
                {em && (
                  <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                    Email DNS {em.all_written ? "written" : "partially written"} · Resend status:{" "}
                    <strong>{em.status}</strong>
                    {em.records.some((r) => !r.ok) && (
                      <span> — {em.records.filter((r) => !r.ok).map((r) => `${r.type} ${r.name}`).join(", ")} failed</span>
                    )}
                  </div>
                )}
              </div>
            );
          })
        ) : (
          <p className="muted">No domains yet — search above to buy your first.</p>
        )}
      </div>
    </div>
  );
}
