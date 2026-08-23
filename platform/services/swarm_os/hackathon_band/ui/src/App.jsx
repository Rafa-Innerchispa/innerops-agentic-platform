import { useCallback, useEffect, useState } from "react";
import { I18nProvider, useI18n } from "./i18n/I18nContext";
import Header from "./components/Header";
import AgentMap from "./components/AgentMap";
import LiveConsole from "./components/LiveConsole";
import BandAuditTrail from "./components/BandAuditTrail";
import RunPanel, { loadExtraEmails, loadExtraPhones } from "./components/RunPanel";
import MemoryProof from "./components/MemoryProof";
import ReportPanel from "./components/ReportPanel";
import CircuitBackground from "./components/CircuitBackground";
import "./styles/dashboard.css";

function Dashboard() {
  const { lang } = useI18n();
  const [status, setStatus] = useState(null);
  const [question, setQuestion] = useState("");
  const [extraPhones, setExtraPhones] = useState(loadExtraPhones);
  const [extraEmails, setExtraEmails] = useState(loadExtraEmails);
  const [running, setRunning] = useState(false);
  const [activeStep, setActiveStep] = useState("");
  const [hoverKey, setHoverKey] = useState(null);
  const [consoleEntries, setConsoleEntries] = useState([]);
  const [report, setReport] = useState("");
  const [lastChatId, setLastChatId] = useState("");
  const [error, setError] = useState("");
  const [questionInit, setQuestionInit] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const r = await fetch("/api/status");
      const data = await r.json();
      setStatus(data);
      if (!questionInit) {
        const suggested = data.suggested_questions?.[lang];
        if (suggested?.[0]) setQuestion(suggested[0]);
        setQuestionInit(true);
      }
    } catch (e) {
      setError(String(e));
    }
  }, [lang, questionInit]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const run = async () => {
    setRunning(true);
    setError("");
    setReport("");
    setActiveStep("chat_created");
    setConsoleEntries([]);
    try {
      const params = new URLSearchParams({
        q: question,
        lang,
        notify_phones: extraPhones.trim(),
        notify_emails: extraEmails.trim(),
      });
      const es = new EventSource(`/api/run/stream?${params.toString()}`);
      es.onmessage = (msg) => {
        const ev = JSON.parse(msg.data);
        if (ev.step) setActiveStep(ev.step);
        if (ev.chat_id) setLastChatId(ev.chat_id);
        if (ev.step === "complete") {
          setReport(ev.result?.report_markdown || "");
          setLastChatId(ev.result?.chat_id || "");
          setActiveStep("complete");
          es.close();
          setRunning(false);
        }
        if (ev.step === "error") {
          setError(ev.error);
          es.close();
          setRunning(false);
        }
      };
      es.onerror = () => {
        setError("SSE error — is API :8200 running?");
        es.close();
        setRunning(false);
      };
    } catch (e) {
      setError(String(e));
      setRunning(false);
    }
  };

  const suggested = status?.suggested_questions?.[lang] || [];

  return (
    <>
      <CircuitBackground />
      <div className="dashboard">
        <Header status={status} />
        <div className="dash-grid">
          <div className="col-main">
            <AgentMap
              agents={status?.agents || []}
              activeStep={activeStep}
              hoverKey={hoverKey}
              setHoverKey={setHoverKey}
            />
            <RunPanel
              question={question}
              setQuestion={setQuestion}
              extraPhones={extraPhones}
              setExtraPhones={setExtraPhones}
              extraEmails={extraEmails}
              setExtraEmails={setExtraEmails}
              suggested={suggested}
              running={running}
              ready={status?.readiness?.ready}
              onRun={run}
              error={error}
            />
            <MemoryProof
              question={question}
              mongoDb={status?.mongo_db}
              mongoStats={status?.mongo_stats}
              docsPath={status?.docs_root}
            />
            <ReportPanel report={report} />
          </div>
          <div className="col-side">
            <LiveConsole entries={consoleEntries} setEntries={setConsoleEntries} />
            <BandAuditTrail lastChatId={lastChatId} running={running} />
          </div>
        </div>
      </div>
    </>
  );
}

export default function App() {
  return (
    <I18nProvider>
      <Dashboard />
    </I18nProvider>
  );
}
