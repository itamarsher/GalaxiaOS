"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { api, type CompanyFile } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

// Category → human label + the order we group them in (mirrors the Drive taxonomy
// under .abos/<company>/). "communications" is the auto-archived outbound comms log.
const CATEGORIES: [string, string][] = [
  ["artifact", "Artifacts"],
  ["financial", "Financials"],
  ["data_room", "Data Room"],
  ["brand", "Brand & Messaging"],
  ["inbox", "Inbox"],
  ["communications", "Communications"],
  ["knowledge", "Knowledge"],
];

const fmtSize = (n: number | null) =>
  n == null ? "" : n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`;

export default function FilesPage() {
  const { id } = useParams<{ id: string }>();
  const [filter, setFilter] = useState<string>("");
  const files = usePoll(() => api.companyFiles(id, filter || undefined), 0, [id, filter]);
  const list = files.data ?? [];

  const grouped = useMemo(() => {
    const by: Record<string, CompanyFile[]> = {};
    for (const f of list) (by[f.category] ??= []).push(f);
    return by;
  }, [list]);

  return (
    <div>
      <h2>Files</h2>
      <p className="muted">
        The company&apos;s external file store (your Google Drive, under <code>.abos/</code>). Every
        deliverable, financial record, data-room document, guideline and received file the agents
        retain — organized for audits and due diligence. Connect Drive in Settings to enable it.
      </p>

      <div className="chatbar">
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All categories</option>
          {CATEGORIES.map(([slug, label]) => (
            <option key={slug} value={slug}>{label}</option>
          ))}
        </select>
        <button onClick={() => files.reload()}>Refresh</button>
      </div>

      {list.length === 0 && (
        <div className="empty">
          No files yet. Once you connect Google Drive in Settings, agents will file documents here.
        </div>
      )}

      {CATEGORIES.filter(([slug]) => grouped[slug]?.length).map(([slug, label]) => (
        <div key={slug} style={{ marginTop: 18 }}>
          <h3 style={{ margin: "0 0 8px" }}>{label}</h3>
          {grouped[slug].map((f) => (
            <div key={f.id} className="card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong>
                  {f.web_url ? (
                    <a href={f.web_url} target="_blank" rel="noreferrer">{f.name}</a>
                  ) : (
                    f.name
                  )}
                </strong>
                <span className="muted" style={{ fontSize: 12 }}>
                  {new Date(f.created_at).toLocaleString()}
                </span>
              </div>
              {f.description && <div className="muted" style={{ marginTop: 4 }}>{f.description}</div>}
              <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                <code>{f.folder_path}</code>
                {f.size_bytes != null && <> · {fmtSize(f.size_bytes)}</>}
                {" · "}{f.mime_type}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
