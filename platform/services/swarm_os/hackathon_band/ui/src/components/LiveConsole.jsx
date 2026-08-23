import { useCallback, useRef, useEffect } from "react";
import { useI18n } from "../i18n/I18nContext";
import { useConsoleWebSocket } from "../hooks/useConsoleWebSocket";

const CAT_COLOR = {
  band: "#e8e8e8",
  mongo: "#7dd3fc",
  featherless: "#a3e635",
  aiml: "#f472b6",
  whatsapp: "#4ade80",
  system: "#94a3b8",
  api: "#fbbf24",
};

export default function LiveConsole({ entries, setEntries }) {
  const { t } = useI18n();
  const bottomRef = useRef(null);
  const onEntry = useCallback(
    (entry) => setEntries((prev) => [...prev.slice(-399), entry]),
    [setEntries]
  );
  const { connected } = useConsoleWebSocket(onEntry);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries]);

  return (
    <section className="panel console-panel">
      <div className="panel-head">
        <h2>{t.sectionConsole}</h2>
        <div className="head-actions">
          <span className={`dot ${connected ? "on" : "off"}`} />
          <span className="muted">{connected ? t.connected : t.disconnected}</span>
          <button type="button" className="ghost" onClick={() => setEntries([])}>
            {t.clearConsole}
          </button>
        </div>
      </div>
      <div className="terminal">
        {entries.length === 0 && (
          <div className="term-line muted">{t.consoleWaiting}</div>
        )}
        {entries.map((e, i) => (
          <div key={`${e.ts}-${i}`} className={`term-line level-${e.level}`}>
            <span className="term-ts">{e.ts?.slice(11, 19)}</span>
            <span
              className="term-cat"
              style={{ color: CAT_COLOR[e.category] || "#ccc" }}
            >
              [{e.category}]
            </span>
            <span className="term-msg">{e.message}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </section>
  );
}
