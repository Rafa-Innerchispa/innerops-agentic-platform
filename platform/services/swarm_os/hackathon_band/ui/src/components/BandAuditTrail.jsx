import { useEffect, useState } from "react";
import { useI18n } from "../i18n/I18nContext";

export default function BandAuditTrail({ lastChatId, running }) {
  const { t } = useI18n();
  const [audit, setAudit] = useState(null);

  useEffect(() => {
    fetch("/api/band/audit")
      .then((r) => r.json())
      .then(setAudit)
      .catch(() => setAudit(null));
    const id = setInterval(() => {
      fetch("/api/band/audit")
        .then((r) => r.json())
        .then(setAudit)
        .catch(() => {});
    }, running ? 2000 : 8000);
    return () => clearInterval(id);
  }, [running, lastChatId]);

  return (
    <section className="panel audit-panel">
      <div className="panel-head">
        <h2>{t.sectionAudit}</h2>
        <span className="badge-live">{t.bandLive}</span>
      </div>
      <div className="audit-grid">
        <div className="audit-item">
          <label>{t.bandLive}</label>
          <strong>{audit?.band_mode || "LIVE"}</strong>
        </div>
        <div className="audit-item">
          <label>REST</label>
          <strong className="mono">{audit?.band_rest_url || "—"}</strong>
        </div>
        <div className="audit-item wide">
          <label>{t.lastRun} · {t.roomId}</label>
          <strong className="mono">{(lastChatId || audit?.last_chat_id) || "—"}</strong>
        </div>
      </div>
      <div className="agent-ids">
        {audit?.agents &&
          Object.entries(audit.agents).map(([k, v]) => (
            <div key={k} className="id-row">
              <span>@{v.name}</span>
              <code>{v.band_id?.slice(0, 8)}…</code>
            </div>
          ))}
      </div>
      <div className="rooms-list">
        {(audit?.audit_rooms || []).slice(0, 4).map((r) => (
          <div key={r.chat_id} className="room-row">
            <code>{r.chat_id?.slice(0, 8)}…</code>
            <span>{r.message_count} {t.messages}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
