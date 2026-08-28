import { useState } from "react";
import { useI18n } from "../i18n/I18nContext";

export default function MemoryProof({ question, mongoDb, mongoStats = {}, docsPath }) {
  const { t } = useI18n();
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetch(`/api/memory/preview?q=${encodeURIComponent(question)}`);
      const data = await r.json();
      setPreview((p) => ({ ...p, ...data }));
    } catch {
      setPreview(null);
    } finally {
      setLoading(false);
    }
  };

  const stats = mongoStats;
  const hits = preview?.hits || [];

  return (
    <section className="panel memory-panel">
      <div className="panel-head">
        <h2>{t.sectionMemory}</h2>
      </div>
      <p className="muted">{t.memoryHint}</p>
      <div className="meta-row">
        <span>{t.mongoDb}: <code>{mongoDb}</code></span>
        <span>{t.docsPath}: <code className="small">{docsPath}</code></span>
      </div>
      {Object.keys(stats).length > 0 && (
        <div className="mongo-stats-grid">
          {Object.entries(stats).map(([coll, n]) => (
            <div key={coll} className="mongo-stat-cell">
              <span className="mongo-stat-name">{coll}</span>
              <span className="mongo-stat-count">{n}</span>
            </div>
          ))}
        </div>
      )}
      <button type="button" className="ghost" onClick={load} disabled={loading}>
        {loading ? "…" : t.previewMemory}
      </button>
      {preview?.corpus && (
        <div className="memory-preview">
          <div className="stat">
            {hits.length || preview.hits?.length || 0} {t.hits} · {preview.corpus_chars} {t.chars}
          </div>
          {hits.length > 0 && (
            <div className="hit-rows">
              <strong>{t.sampleDocs}</strong>
              {hits.slice(0, 4).map((h) => (
                <div key={`${h.source}-${h.id}`} className="hit-row">
                  <code>{h.source}</code>
                  {h.id && <span className="hit-id">{h.id}</span>}
                  <p>{(h.text || "").slice(0, 160)}…</p>
                </div>
              ))}
            </div>
          )}
          <div className="sources-list">
            <strong>{t.sources}</strong>
            <ul>
              {(preview.sources || []).slice(0, 8).map((s) => (
                <li key={s}><code>{s}</code></li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}
