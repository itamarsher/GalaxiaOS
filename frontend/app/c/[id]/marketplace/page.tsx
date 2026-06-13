"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, fmtUsd, type AgentListing } from "@/lib/api";

export default function MarketplacePage() {
  const { id } = useParams<{ id: string }>();
  const [items, setItems] = useState<AgentListing[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [hiring, setHiring] = useState<string | null>(null);
  const [hired, setHired] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.marketplace().then((l) => { setItems(l); setLoaded(true); }).catch((e) => setError(String(e)));
  }, []);

  const hire = async (listingId: string) => {
    setError(null);
    setHiring(listingId);
    try {
      await api.hireAgent(id, listingId);
      setHired((h) => ({ ...h, [listingId]: true }));
    } catch (e) {
      setError(String(e));
    } finally {
      setHiring(null);
    }
  };

  const fmtScore = (v: number | null) => (v == null ? "—" : v.toFixed(2));

  return (
    <div>
      <h2>Agent Marketplace</h2>
      <p className="muted">Hire specialised agents into your org. Hired agents report to your CEO and bill a flat fee per invocation.</p>
      {error && <div className="empty">{error}</div>}
      {loaded && items.length === 0 && <div className="empty">No listings available.</div>}
      {items.map((l) => (
        <div key={l.id} className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <strong>{l.name}</strong>{" "}
              <span className="pill">{l.role}</span>
            </div>
            <span className="muted" style={{ fontSize: 12 }}>{l.provider}</span>
          </div>
          <p className="muted" style={{ margin: "8px 0" }}>{l.description}</p>
          <div className="muted" style={{ fontSize: 12 }}>
            trust {fmtScore(l.trust)} · accuracy {fmtScore(l.accuracy)} · roi {fmtScore(l.roi)} · reliability {fmtScore(l.reliability)}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10 }}>
            <strong>{fmtUsd(l.price_cents)} / invocation</strong>
            <button
              disabled={hiring === l.id || hired[l.id]}
              onClick={() => hire(l.id)}
            >
              {hired[l.id] ? "Hired" : hiring === l.id ? "Hiring…" : "Hire"}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
