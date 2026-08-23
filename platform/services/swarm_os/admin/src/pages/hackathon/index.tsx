import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button, Space, Typography, message } from "antd";
import {
  CommentOutlined,
  MailOutlined,
  CarOutlined,
  FileTextOutlined,
  PlayCircleOutlined,
} from "@ant-design/icons";
import { useLang, type Lang } from "../../i18n/LangContext";
import { DemoWizard, type GuidedTourPayload } from "../../components/DemoWizard";
import { getApiBase, getApiRoot } from "../../lib/api";
import { formatApiError, parseApiResponse } from "../../lib/parseApiError";

type Droid = {
  id: string;
  code: string;
  name: string;
  label: string;
  role: string;
  state?: string;
  live?: boolean;
  demo_only?: boolean;
};

type ActivityEntry = {
  ts: string;
  droid_id: string;
  droid_code: string;
  message: string;
  level?: string;
};

type TourSummary = {
  inspection_id?: string;
  quote_serial?: string;
  quote_total?: number;
  client_name?: string;
  quote_id?: string;
  visit_id?: string;
  report_id?: string;
};

type GeminiPlan = {
  mission_summary?: string;
  client_hint?: string;
  equipment?: string[];
  source?: string;
  model?: string;
};

const COPY = {
  es: {
    title: "InnerOS — Enjambre de agentes",
    subtitle:
      "Ocho agentes especializados orquestan las operaciones de PC Doctor. Esta vista muestra el estado en tiempo real; el trabajo real se hace en el menú lateral.",
    thesisTitle: "Arquitectura soberana (honesta)",
    thesis: [
      "8 agentes especializados orquestados LOCALMENTE con CrewAI en servidor soberano (no depende de la nube para ejecutar).",
      "Gemini se usa en la capa de RAZONAMIENTO (asistente, clasificación) — no reemplaza la ejecución local ni las tools reales.",
      "Integración partner MongoDB MCP para consultas y trazabilidad de datos operativos.",
      "Diseñado/prototipado en Google AI Studio (Agent Builder); implementación y demo en stack local PC Doctor.",
    ],
    runTour: "Iniciar demo guiada",
    wizardHint: "Paso a paso: correo → cliente (SRI) → catálogo → cotización real + WhatsApp",
    reset: "Reiniciar estados",
    operate: "Operar el sistema",
    dc: "Centro de Datos — chat, voz Whisper, ERP",
    email: "Correos y alertas WhatsApp",
    visits: "Visitas de campo",
    quotes: "Cotizaciones",
    reports: "Informes técnicos",
    selected: "Agente seleccionado",
    clickHint: "Haz clic en una bola para ver su rol",
    missionLog: "Registro de misión",
    geminiPlan: "Plan Gemini",
    running: "Ejecutando misión multi-droid…",
    resultTitle: "Resultado de la misión",
    states: {
      idle: "En espera",
      working: "Trabajando",
      done: "Completado",
      error: "Revisar",
      roadmap: "En roadmap",
    },
    droids: {
      d1: "Monitorea correos IMAP, filtra spam y detecta cotizaciones urgentes.",
      d2: "Transcribe voz de técnicos en campo (Whisper) y estructura hallazgos.",
      d3: "Orquesta el flujo: clientes, inspecciones y datos en MongoDB.",
      d4: "Genera informes técnicos y documentos PDF para el cliente.",
      d5: "Valida RUC/SRI, calcula IVA y arma cotizaciones.",
      d6: "Responde con conocimiento (RAG) y búsqueda web técnica.",
      d7: "Firma electrónica XAdES — integración fiscal en desarrollo.",
      d8: "Envía resúmenes y alertas por WhatsApp al cliente.",
    },
    tourOk: "Demostración completada",
    tourFail: "Error en demostración",
    loadFail: "No se pudo cargar agentes",
  },
  en: {
    title: "InnerOS — Agent swarm",
    subtitle:
      "Eight specialized agents orchestrate PC Doctor operations. This view shows live status; real work happens in the side menu.",
    thesisTitle: "Sovereign architecture (honest)",
    thesis: [
      "8 specialized agents orchestrated LOCALLY with CrewAI on a sovereign server (cloud not required to execute).",
      "Gemini powers the REASONING layer (assistant, classification) — it does not replace local execution or real tools.",
      "MongoDB MCP partner integration for operational data queries and traceability.",
      "Designed/prototyped in Google AI Studio (Agent Builder); built and demoed on the local PC Doctor stack.",
    ],
    runTour: "Start guided demo",
    wizardHint: "Step-by-step: email → client (SRI) → catalog → real quote + WhatsApp",
    reset: "Reset status",
    operate: "Open live modules",
    dc: "Data Center — chat, Whisper voice, ERP",
    email: "Email monitor & WhatsApp alerts",
    visits: "Field visits",
    quotes: "Quotes",
    reports: "Technical reports",
    selected: "Selected agent",
    clickHint: "Click a ball to see its role",
    missionLog: "Mission log",
    geminiPlan: "Gemini plan",
    running: "Running multi-droid mission…",
    resultTitle: "Mission result",
    states: {
      idle: "Idle",
      working: "Working",
      done: "Done",
      error: "Check",
      roadmap: "Roadmap",
    },
    droids: {
      d1: "Monitors IMAP mail, filters spam, detects urgent quotes.",
      d2: "Transcribes field voice (Whisper) and structures findings.",
      d3: "Orchestrates flow: clients, inspections, MongoDB data.",
      d4: "Generates technical reports and PDF documents.",
      d5: "Validates tax ID/SRI, VAT math, builds quotes.",
      d6: "Knowledge answers (RAG) and technical web search.",
      d7: "XAdES e-invoicing — fiscal signing on roadmap.",
      d8: "Sends summaries and WhatsApp alerts to clients.",
    },
    tourOk: "Demo completed",
    tourFail: "Demo failed",
    loadFail: "Could not load agents",
  },
} as const;

const BALL_POS: Record<string, { x: number; y: number; size: number; color: string }> = {
  d1: { x: 18, y: 12, size: 88, color: "#22d3ee" },
  d2: { x: 72, y: 12, size: 88, color: "#3b82f6" },
  d3: { x: 50, y: 38, size: 110, color: "#f8fafc" },
  d4: { x: 12, y: 58, size: 84, color: "#a855f7" },
  d5: { x: 38, y: 72, size: 84, color: "#ec4899" },
  d6: { x: 62, y: 72, size: 84, color: "#6366f1" },
  d7: { x: 82, y: 58, size: 80, color: "#8b5cf6" },
  d8: { x: 50, y: 88, size: 84, color: "#22c55e" },
};

const SWARM_W = 720;
const SWARM_H = 420;

const LOG_COLORS: Record<string, string> = {
  gemini: "#a78bfa",
  success: "#4ade80",
  warn: "#fbbf24",
  error: "#f87171",
  info: "#94a3b8",
};

function stateLabel(d: Droid, lang: Lang): string {
  const s = COPY[lang].states;
  if (d.demo_only && !d.live) return s.roadmap;
  const st = d.state || "idle";
  if (st === "idle") return s.idle;
  if (st === "working") return s.working;
  if (st === "done") return s.done;
  if (st === "error") return s.error;
  return st;
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts.slice(11, 19) || ts;
  }
}

export function HackathonPage() {
  const { lang } = useLang();
  const [droids, setDroids] = useState<Droid[]>([]);
  const [tourLoading, setTourLoading] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string>("d3");
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [activityLog, setActivityLog] = useState<ActivityEntry[]>([]);
  const [geminiPlan, setGeminiPlan] = useState<GeminiPlan | null>(null);
  const [tourSummary, setTourSummary] = useState<TourSummary | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const t = COPY[lang];
  const API = getApiBase();

  const refresh = useCallback(() => {
    fetch(`${API}/hackathon/droids/status`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json();
      })
      .then((d) => setDroids(d.droids || []))
      .catch(() => message.error(t.loadFail));
  }, [API, t.loadFail]);

  const resetStates = useCallback(() => {
    fetch(`${API}/hackathon/droids/reset`, { method: "POST" })
      .then(() => refresh())
      .catch(() => {});
  }, [API, refresh]);

  useEffect(() => {
    resetStates();
    const iv = setInterval(refresh, 10000);
    return () => clearInterval(iv);
  }, [refresh, resetStates]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [activityLog]);

  const scrollToLog = () => {
    setTimeout(() => {
      logRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 100);
  };

  const pushLiveLog = (message: string, droidId = "d3", level = "info") => {
    const entry: ActivityEntry = {
      ts: new Date().toISOString(),
      droid_id: droidId,
      droid_code: `D${droidId.replace("d", "")}`,
      message,
      level,
    };
    setActivityLog((prev) => [...prev, entry]);
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  };

  const replayActivityLog = async (entries: ActivityEntry[]) => {
    for (const entry of entries) {
      setActivityLog((prev) => [...prev, entry]);
      if (entry.droid_id) {
        setDroids((prev) =>
          prev.map((d) =>
            d.id === entry.droid_id
              ? { ...d, state: entry.level === "error" ? "error" : entry.level === "success" ? "done" : "working" }
              : d,
          ),
        );
        if (entry.level === "success" || entry.message.toLowerCase().includes("complete")) {
          setDroids((prev) => prev.map((d) => ({ ...d, state: d.state === "working" ? "done" : d.state })));
        }
      }
      logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
      await new Promise((r) => setTimeout(r, 580));
    }
    refresh();
  };

  const runTour = async (payload?: GuidedTourPayload) => {
    setTourLoading(true);
    setActivityLog([]);
    setGeminiPlan(null);
    setTourSummary(null);
    scrollToLog();
    pushLiveLog("Mission starting — connecting agents…", "d3", "info");
    pushLiveLog("Polling mail gatekeeper / Gemini plan…", "d1", "info");
    resetStates();
    if (!payload) {
      setWizardOpen(true);
      setTourLoading(false);
      return;
    }
    const body: GuidedTourPayload = payload;
    try {
      const res = await fetch(`${API}/hackathon/tour/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const { ok, data, raw } = await parseApiResponse(res);
      if (!ok) throw new Error(formatApiError(data, raw, res.status));

      const plan = (data.gemini_plan as GeminiPlan) || null;
      setGeminiPlan(plan);
      setTourSummary((data.summary as TourSummary) || null);

      const entries = (data.activity_log as ActivityEntry[]) || [];
      setActivityLog([]);
      if (entries.length) {
        await replayActivityLog(entries);
      } else {
        pushLiveLog("No activity log returned from server", "d3", "error");
        refresh();
      }
      scrollToLog();

      const inspectionId = (data.inspection_id as string) || "OK";
      message.success(`${t.tourOk} — ${inspectionId}`);
    } catch (e: unknown) {
      message.error(e instanceof Error ? `${t.tourFail}: ${e.message}` : t.tourFail);
      refresh();
    } finally {
      setTourLoading(false);
    }
  };

  const links = [
    { to: "/datacenter", label: t.dc, icon: <CommentOutlined /> },
    { to: "/email", label: t.email, icon: <MailOutlined /> },
    { to: "/visits", label: t.visits, icon: <CarOutlined /> },
    { to: "/quotes", label: t.quotes, icon: <FileTextOutlined /> },
    { to: "/reports", label: t.reports, icon: <FileTextOutlined /> },
  ];

  const selected = droids.find((d) => d.id === selectedId) || droids.find((d) => d.id === "d3");
  const center = BALL_POS.d3;

  return (
    <div style={{ color: "#e2e8f0" }}>
      <Typography.Title level={2} style={{ color: "#f8fafc", margin: 0 }}>
        {t.title}
      </Typography.Title>
      <Typography.Paragraph style={{ color: "#94a3b8", maxWidth: 720, margin: "8px 0 16px" }}>
        {t.subtitle}
      </Typography.Paragraph>

      <div
        style={{
          maxWidth: 720,
          marginBottom: 20,
          padding: "14px 18px",
          borderRadius: 12,
          background: "rgba(30,58,95,0.55)",
          border: "1px solid #334155",
        }}
      >
        <Typography.Text strong style={{ color: "#e2e8f0", display: "block", marginBottom: 8 }}>
          {t.thesisTitle}
        </Typography.Text>
        <ul style={{ margin: 0, paddingLeft: 20, color: "#cbd5e1", fontSize: 13, lineHeight: 1.6 }}>
          {t.thesis.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </div>

      <Typography.Title level={5} style={{ color: "#f1f5f9", marginBottom: 10 }}>
        {t.operate}
      </Typography.Title>
      <Space wrap style={{ marginBottom: 20 }}>
        {links.map((l) => (
          <Link key={l.to} to={l.to}>
            <Button size="large" icon={l.icon}>
              {l.label}
            </Button>
          </Link>
        ))}
        <Button href={`${getApiRoot()}/docs`} target="_blank">
          API
        </Button>
      </Space>

      <Space wrap style={{ marginBottom: 8 }}>
        <Button
          type="primary"
          size="large"
          icon={<PlayCircleOutlined />}
          loading={tourLoading}
          onClick={() => setWizardOpen(true)}
        >
          {t.runTour}
        </Button>
        <Button onClick={resetStates}>{t.reset}</Button>
      </Space>
      <Typography.Paragraph style={{ color: "#94a3b8", fontSize: 12, marginBottom: 12 }}>{t.wizardHint}</Typography.Paragraph>

      <DemoWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        loading={tourLoading}
        onRun={(p) => {
          setWizardOpen(false);
          setTimeout(() => runTour(p), 150);
        }}
      />

      <div
        id="mission-log-panel"
        style={{
          maxWidth: 720,
          marginBottom: 16,
          borderRadius: 12,
          border: tourLoading ? "2px solid #22d3ee" : "1px solid #334155",
          background: "#0a0f1a",
          overflow: "hidden",
          boxShadow: tourLoading ? "0 0 24px rgba(34,211,238,0.25)" : undefined,
        }}
      >
        <div
          style={{
            padding: "10px 14px",
            borderBottom: "1px solid #334155",
            background: "rgba(15,23,42,0.95)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <Typography.Text strong style={{ color: "#e2e8f0", fontFamily: "monospace" }}>
            {t.missionLog}
          </Typography.Text>
          {tourLoading && (
            <Typography.Text style={{ color: "#22d3ee", fontSize: 12 }}>{t.running}</Typography.Text>
          )}
        </div>

        {geminiPlan && (
          <div
            style={{
              padding: "10px 14px",
              borderBottom: "1px solid #1e293b",
              background: "rgba(88,28,135,0.15)",
            }}
          >
            <Typography.Text style={{ color: "#a78bfa", fontSize: 11, fontWeight: 700 }}>
              ✦ {t.geminiPlan}
              {geminiPlan.source === "gemini" ? ` (${geminiPlan.model || "Gemini"})` : ` [${geminiPlan.source}]`}
            </Typography.Text>
            <Typography.Paragraph style={{ color: "#ddd6fe", margin: "4px 0 0", fontSize: 13 }}>
              {geminiPlan.mission_summary}
            </Typography.Paragraph>
          </div>
        )}

        <div
          ref={logRef}
          className="mission-log-body"
          style={{
            maxHeight: 300,
            overflowY: "auto",
            padding: "10px 14px",
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
            fontSize: 12,
            lineHeight: 1.7,
          }}
        >
          {activityLog.length === 0 && !tourLoading && (
            <Typography.Text type="secondary" style={{ color: "#475569" }}>
              {lang === "en" ? "Press Start guided demo — Mission Log appears here in real time." : "Pulsa Iniciar demo guiada — el log aparece aquí en tiempo real."}
            </Typography.Text>
          )}
          {tourLoading && activityLog.length <= 2 && (
            <Typography.Text style={{ color: "#22d3ee" }}>
              {lang === "en" ? "▌ Agents working…" : "▌ Agentes trabajando…"}
            </Typography.Text>
          )}
          {activityLog.map((entry, i) => (
            <div key={`${entry.ts}-${i}`} style={{ marginBottom: 2 }}>
              <span style={{ color: "#64748b" }}>{formatTs(entry.ts)}</span>{" "}
              <span style={{ color: BALL_POS[entry.droid_id]?.color || "#94a3b8", fontWeight: 700 }}>
                [{entry.droid_code}]
              </span>{" "}
              <span style={{ color: LOG_COLORS[entry.level || "info"] || "#cbd5e1" }}>{entry.message}</span>
            </div>
          ))}
        </div>

        {tourSummary && !tourLoading && (
          <div
            style={{
              padding: "12px 14px",
              borderTop: "1px solid #334155",
              background: "rgba(20,83,45,0.2)",
            }}
          >
            <Typography.Text strong style={{ color: "#4ade80", display: "block", marginBottom: 6 }}>
              {t.resultTitle}
            </Typography.Text>
            <Typography.Text style={{ color: "#cbd5e1", fontSize: 13, display: "block" }}>
              inspection: {tourSummary.inspection_id} · client: {tourSummary.client_name} · quote:{" "}
              {tourSummary.quote_serial} · USD {Number(tourSummary.quote_total || 0).toFixed(2)}
              {tourSummary.quote_id && (
                <>
                  {" "}
                  · quote_id: <code style={{ color: "#86efac" }}>{tourSummary.quote_id}</code>
                </>
              )}
            </Typography.Text>
            {tourSummary.quote_id && (
              <Typography.Text style={{ color: "#94a3b8", fontSize: 12, display: "block", marginTop: 4 }}>
                Cotización persistida en MongoDB — serial {tourSummary.quote_serial || "—"} para{" "}
                {tourSummary.client_name || "cliente"}
              </Typography.Text>
            )}
            <Space wrap style={{ marginTop: 8 }}>
              <Link to="/quotes">
                <Button size="small">Quotes</Button>
              </Link>
              <Link to="/visits">
                <Button size="small">Visits</Button>
              </Link>
              <Link to="/reports">
                <Button size="small">Reports</Button>
              </Link>
            </Space>
          </div>
        )}
      </div>

      {selected && (
        <div
          style={{
            maxWidth: 720,
            margin: "0 auto 16px",
            padding: "16px 20px",
            borderRadius: 12,
            background: "rgba(15,23,42,0.85)",
            border: `2px solid ${BALL_POS[selected.id]?.color || "#64748b"}`,
            boxShadow: `0 0 28px ${BALL_POS[selected.id]?.color || "#64748b"}44`,
          }}
        >
          <Typography.Text style={{ color: "#94a3b8", fontSize: 12 }}>{t.selected}</Typography.Text>
          <Typography.Title level={4} style={{ color: "#f8fafc", margin: "4px 0 6px" }}>
            {selected.code} — {selected.name}
          </Typography.Title>
          <Typography.Text style={{ color: BALL_POS[selected.id]?.color, marginRight: 12 }}>
            {stateLabel(selected, lang)}
          </Typography.Text>
          <Typography.Paragraph style={{ color: "#e2e8f0", margin: "10px 0 0", fontSize: 15 }}>
            {COPY[lang].droids[selected.id as keyof typeof COPY["es"]["droids"]]}
          </Typography.Paragraph>
        </div>
      )}

      <div
        style={{
          position: "relative",
          height: SWARM_H,
          maxWidth: SWARM_W,
          margin: "0 auto 28px",
          borderRadius: 16,
          background: "rgba(15,23,42,0.5)",
          border: "1px solid #334155",
        }}
      >
        <svg
          viewBox={`0 0 ${SWARM_W} ${SWARM_H}`}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
        >
          {Object.entries(BALL_POS)
            .filter(([id]) => id !== "d3")
            .map(([id, pos]) => {
              const cx = (center.x / 100) * SWARM_W;
              const cy = (center.y / 100) * SWARM_H;
              const tx = (pos.x / 100) * SWARM_W;
              const ty = (pos.y / 100) * SWARM_H;
              const active = selectedId === id || hoverId === id;
              return (
                <line
                  key={`line-${id}`}
                  x1={cx}
                  y1={cy}
                  x2={tx}
                  y2={ty}
                  stroke={pos.color}
                  strokeWidth={active ? 2.5 : 1.2}
                  strokeOpacity={active ? 0.85 : 0.35}
                  strokeDasharray={active ? undefined : "6 4"}
                />
              );
            })}
        </svg>

        {droids.map((d) => {
          const pos = BALL_POS[d.id];
          if (!pos) return null;
          const desc = COPY[lang].droids[d.id as keyof typeof COPY["es"]["droids"]];
          const st = d.state || "idle";
          const isHover = hoverId === d.id;
          const isSelected = selectedId === d.id;
          const glow =
            st === "working"
              ? `0 0 24px ${pos.color}`
              : st === "error"
                ? "0 0 16px #ef4444"
                : isHover || isSelected
                  ? `0 0 20px ${pos.color}aa`
                  : "none";
          const scale = isHover || isSelected ? 1.08 : 1;
          return (
            <div
              key={d.id}
              title={desc}
              role="button"
              tabIndex={0}
              onClick={() => setSelectedId(d.id)}
              onKeyDown={(e) => e.key === "Enter" && setSelectedId(d.id)}
              onMouseEnter={() => setHoverId(d.id)}
              onMouseLeave={() => setHoverId(null)}
              style={{
                position: "absolute",
                left: `${pos.x}%`,
                top: `${pos.y}%`,
                transform: `translate(-50%, -50%) scale(${scale})`,
                width: pos.size,
                height: pos.size,
                borderRadius: "50%",
                background: `radial-gradient(circle at 35% 35%, ${pos.color}dd, ${pos.color}44)`,
                border: `2px solid ${pos.color}`,
                boxShadow: glow,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                textAlign: "center",
                padding: 6,
                cursor: "pointer",
                transition: "transform 0.2s ease, box-shadow 0.2s ease",
                zIndex: isSelected ? 3 : 2,
              }}
            >
              <div style={{ fontSize: 11, fontWeight: 800, color: d.id === "d3" ? "#0f172a" : "#fff" }}>{d.code}</div>
              <div
                style={{
                  fontSize: 9,
                  fontWeight: 600,
                  color: d.id === "d3" ? "#334155" : "#e2e8f0",
                  lineHeight: 1.1,
                }}
              >
                {d.label}
              </div>
              <div style={{ fontSize: 8, marginTop: 4, color: d.id === "d3" ? "#475569" : "#cbd5e1" }}>
                {stateLabel(d, lang)}
              </div>
            </div>
          );
        })}
      </div>

      <Typography.Paragraph type="secondary" style={{ textAlign: "center", maxWidth: 720, margin: "0 auto", color: "#64748b" }}>
        {t.clickHint}
      </Typography.Paragraph>
    </div>
  );
}
