import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  AudioOutlined,
  CarOutlined,
  DownloadOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  LoginOutlined,
  PlusOutlined,
  SendOutlined,
  ShoppingOutlined,
  TeamOutlined,
  AppstoreOutlined,
  ShopOutlined,
  PaperClipOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Input, List, Modal, Space, Switch, Typography, message } from "antd";

import { useLang } from "../../i18n/LangContext";
import { getApiBase } from "../../lib/api";

const API = getApiBase();
const TOKEN_KEY = "ralphi_token";
const SESSION_KEY = "ralphi_chat_session";

type ChatMsg = { role: "user" | "assistant"; text: string };
type ChatSession = { session_id: string; title: string; message_count?: number; updated_at?: string };

function authHeaders(): Record<string, string> {
  const t = localStorage.getItem(TOKEN_KEY);
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export function DataCenterPage() {
  const { lang, pages } = useLang();
  const dc = pages.datacenter;
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(localStorage.getItem(SESSION_KEY));
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [lastTranscript, setLastTranscript] = useState("");
  const [voiceAgent, setVoiceAgent] = useState(false);
  const [secureCtx, setSecureCtx] = useState(true);
  const [loginOpen, setLoginOpen] = useState(false);
  const [user, setUser] = useState<string | null>(null);
  const [loginForm, setLoginForm] = useState({ username: "demo", password: "RalphiDemo2026" });
  const [pendingConfirm, setPendingConfirm] = useState(false);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const loadSessions = useCallback(async () => {
    const res = await fetch(`${API}/chat/sessions`, { headers: authHeaders() });
    const d = await res.json();
    setSessions(d.sessions || []);
    return d.sessions as ChatSession[];
  }, []);

  const loadHistory = useCallback(async (sid: string) => {
    const res = await fetch(`${API}/chat/history?session_id=${sid}`, { headers: authHeaders() });
    const d = await res.json();
    const hist = (d.messages || []).map((m: { role: string; text: string }) => ({
      role: m.role as "user" | "assistant",
      text: m.text,
    }));
    setMessages(hist.length ? hist : [{ role: "assistant", text: dc.welcome }]);
    setSessionId(sid);
    localStorage.setItem(SESSION_KEY, sid);
  }, []);

  useEffect(() => {
    setSecureCtx(window.isSecureContext);
    const t = localStorage.getItem(TOKEN_KEY);
    if (t) {
      fetch(`${API}/auth/me`, { headers: authHeaders() })
        .then((r) => r.json())
        .then((d) => setUser(d.user?.username || null))
        .catch(() => {});
    }
    (async () => {
      const list = await loadSessions();
      const sid = sessionId || list[0]?.session_id;
      if (sid) await loadHistory(sid);
      else {
        const res = await fetch(`${API}/chat/sessions`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({ title: "Nueva conversación" }),
        });
        const s = await res.json();
        await loadHistory(s.session_id);
        await loadSessions();
      }
    })().catch(() => setMessages([{ role: "assistant", text: dc.welcome }]));
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const persist = async (role: string, text: string) => {
    if (!sessionId) return;
    await fetch(`${API}/chat/append`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ role, text, session_id: sessionId }),
    }).catch(() => {});
  };

  const appendMsg = (role: "user" | "assistant", text: string) => {
    setMessages((m) => [...m, { role, text }]);
    persist(role, text);
  };

  const newChat = async () => {
    const res = await fetch(`${API}/chat/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ title: "Nueva conversación" }),
    });
    const s = await res.json();
    await loadSessions();
    setMessages([{ role: "assistant", text: dc.welcome }]);
    setSessionId(s.session_id);
    localStorage.setItem(SESSION_KEY, s.session_id);
  };

  const exportChat = () => {
    if (!sessionId) return;
    window.open(`${API}/chat/sessions/${sessionId}/export`, "_blank");
  };

  const isCreateIntent = (t: string) =>
    /crear|nuevo\s+cliente|cliente\s+nuevo|ruc|c[eé]dula|tel[eé]fono|registrar/i.test(t);

  const send = async (text: string, confirm = false) => {
    const msg = text.trim();
    if (!msg) return;
    appendMsg("user", msg);
    setInput("");
    setLoading(true);
    try {
      const useVoiceAgent =
        pendingConfirm ||
        (voiceAgent && isCreateIntent(msg)) ||
        (confirm || /^(confirmar|sí|si|ok|dale)$/i.test(msg));
      const endpoint = useVoiceAgent ? `${API}/voice/agent/text` : `${API}/assistant/chat`;
      const body = useVoiceAgent
        ? { text: msg, confirm: confirm || pendingConfirm || /^(confirmar|sí|si|ok|dale)$/i.test(msg) }
        : { message: msg, session_id: sessionId };
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      const base = data.reply || data.error || "Sin respuesta";
      const reply = data.source ? `${base}\n\n— motor: ${data.source}` : base;
      appendMsg("assistant", reply);
      setPendingConfirm(!!data.needs_confirm);
      if (data.transcript) setLastTranscript(data.transcript);
      loadSessions();
    } catch (e) {
      message.error(String(e));
    } finally {
      setLoading(false);
    }
  };

  const uploadFile = async (file: File) => {
    if (!sessionId) return;
    setLoading(true);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch(`${API}/chat/sessions/${sessionId}/upload`, {
        method: "POST",
        body: fd,
        headers: authHeaders(),
      });
      const data = await res.json();
      if (data.preview) {
        setMessages((m) => [...m, { role: "assistant", text: data.preview }]);
        loadSessions();
        message.success(`Archivo guardado: ${file.name}`);
      }
    } catch (e) {
      message.error(String(e));
    } finally {
      setLoading(false);
    }
  };

  const transcribeBlob = async (blob: Blob) => {
    const fd = new FormData();
    fd.append("audio_file", blob, "grabacion.webm");
    setLoading(true);
    try {
      if (voiceAgent) {
        const res = await fetch(`${API}/voice/agent`, { method: "POST", body: fd, headers: authHeaders() });
        const data = await res.json();
        setLastTranscript(data.transcript || "");
        appendMsg("user", `[voz] ${data.transcript || ""}`);
        appendMsg("assistant", data.reply || "");
        setPendingConfirm(!!data.needs_confirm);
        if (data.transcript) setInput(data.transcript);
      } else {
        const res = await fetch(`${API}/voice/transcribe`, { method: "POST", body: fd });
        const data = await res.json();
        setLastTranscript(data.text || "");
        setInput(data.text || "");
        message.success("Transcripción lista — revisa y envía");
      }
    } catch (e) {
      message.error(`Whisper: ${e}`);
    } finally {
      setLoading(false);
    }
  };

  const startRecord = async () => {
    if (!window.isSecureContext) {
      message.warning("Activa el flag de Chrome para grabar en http://192.168.1.4");
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true } });
      const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "audio/mp4";
      const rec = new MediaRecorder(stream, { mimeType: mime });
      chunksRef.current = [];
      rec.ondataavailable = (e) => e.data.size && chunksRef.current.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        await transcribeBlob(new Blob(chunksRef.current, { type: mime }));
      };
      mediaRef.current = rec;
      rec.start();
      setRecording(true);
    } catch (err) {
      message.error(`Micrófono bloqueado — usa Subir audio. ${err}`);
    }
  };

  const doLogin = async () => {
    const res = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(loginForm),
    });
    if (!res.ok) {
      message.error("Login fallido");
      return;
    }
    const data = await res.json();
    localStorage.setItem(TOKEN_KEY, data.token);
    setUser(data.user.username);
    setLoginOpen(false);
    message.success(`Hola ${data.user.display_name}`);
    loadSessions();
  };

  return (
    <div style={{ display: "flex", minHeight: "calc(100vh - 120px)" }}>
      <div style={{ width: 260, borderRight: "1px solid #334155", padding: 12, background: "rgba(15,23,42,0.9)" }}>
        <Button type="primary" icon={<PlusOutlined />} block onClick={newChat} style={{ marginBottom: 12 }}>
          {dc.newChat}
        </Button>
        <List
          size="small"
          dataSource={sessions}
          renderItem={(s) => (
            <List.Item
              style={{
                cursor: "pointer",
                padding: "8px 10px",
                borderRadius: 6,
                background: s.session_id === sessionId ? "rgba(59,130,246,0.35)" : "transparent",
              }}
              onClick={() => loadHistory(s.session_id)}
            >
              <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", width: "100%" }}>
                {s.title || "Sin título"}
              </div>
            </List.Item>
          )}
        />
        {sessionId && (
          <Button icon={<DownloadOutlined />} block style={{ marginTop: 12 }} onClick={exportChat}>
            {dc.export}
          </Button>
        )}
      </div>

      <div style={{ flex: 1, padding: 24, maxWidth: 960 }}>
        <Typography.Title level={3}>{dc.title}</Typography.Title>
        <Space style={{ marginBottom: 12 }} wrap>
          <span>{dc.voiceAgent}</span>
          <Switch checked={voiceAgent} onChange={setVoiceAgent} />
          <Button icon={<LoginOutlined />} onClick={() => setLoginOpen(true)}>
            {user ? user : dc.login}
          </Button>
        </Space>

        {!secureCtx && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message="Micrófono en Chrome"
            description={<>Flag: <code>chrome://flags/#unsafely-treat-insecure-origin-as-secure</code> → <code>http://192.168.1.4:5173</code></>}
          />
        )}

        {pendingConfirm && (
          <Alert
            type="success"
            message="Confirmación pendiente"
            action={<Button size="small" onClick={() => send("confirmar", true)}>Confirmar</Button>}
            style={{ marginBottom: 12 }}
          />
        )}

        <Card size="small" title={dc.quickErp} style={{ marginBottom: 16 }}>
          <Space wrap>
            <Link to="/clients"><Button icon={<TeamOutlined />}>{dc.erpClients}</Button></Link>
            <Link to="/visits"><Button icon={<CarOutlined />}>{dc.erpVisits}</Button></Link>
            <Link to="/reports"><Button icon={<FileSearchOutlined />}>{dc.erpReports}</Button></Link>
            <Link to="/inventory"><Button icon={<ShoppingOutlined />}>{dc.erpInventory}</Button></Link>
            <Link to="/catalog"><Button icon={<AppstoreOutlined />}>{dc.erpCatalog}</Button></Link>
            <Link to="/suppliers"><Button icon={<ShopOutlined />}>{dc.erpSuppliers}</Button></Link>
            <Link to="/quotes"><Button icon={<FileTextOutlined />}>{dc.erpQuotes}</Button></Link>
          </Space>
        </Card>

        <Card style={{ minHeight: 380, marginBottom: 16, background: "rgba(15,23,42,0.6)", maxHeight: 480, overflowY: "auto" }}>
          {messages.map((m, i) => (
            <div key={i} style={{ marginBottom: 12, textAlign: m.role === "user" ? "right" : "left" }}>
              <span
                style={{
                  display: "inline-block",
                  padding: "8px 12px",
                  borderRadius: 8,
                  background: m.role === "user" ? "#1e3a8a" : "rgba(30,41,59,0.9)",
                  color: m.role === "user" ? "#fff" : "#e2e8f0",
                  border: m.role === "user" ? "none" : "1px solid #334155",
                  maxWidth: "85%",
                  whiteSpace: "pre-wrap",
                  textAlign: "left",
                }}
              >
                {m.text}
              </span>
            </div>
          ))}
          <div ref={chatEndRef} />
        </Card>

        <Input.TextArea rows={2} value={input} onChange={(e) => setInput(e.target.value)} placeholder={dc.placeholder} onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send(input); } }} />
        <Space style={{ marginTop: 12 }} wrap>
          <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={() => send(input)}>
            {dc.send}
          </Button>
          <Button danger={recording} icon={<AudioOutlined />} onClick={recording ? () => { mediaRef.current?.stop(); setRecording(false); } : startRecord} disabled={loading}>
            {recording ? dc.stop : dc.record}
          </Button>
          <label>
            <input type="file" accept="audio/*" hidden onChange={async (e) => { const f = e.target.files?.[0]; if (f) await transcribeBlob(f); }} />
            <Button>{dc.uploadAudio}</Button>
          </label>
          <label>
            <input type="file" accept=".pdf,.txt,.md,.csv,.json,.jpg,.jpeg,.png,.webp" hidden onChange={async (e) => { const f = e.target.files?.[0]; if (f) await uploadFile(f); }} />
            <Button icon={<PaperClipOutlined />}>{dc.uploadFile}</Button>
          </label>
        </Space>

        <Typography.Paragraph type="secondary" style={{ marginTop: 12, fontSize: 12 }}>
          {dc.footerNote}
        </Typography.Paragraph>
      </div>

      <Modal title={dc.loginTitle} open={loginOpen} onCancel={() => setLoginOpen(false)} onOk={doLogin} okText={dc.loginOk}>
        <p><strong>{dc.loginDemo}:</strong> demo / RalphiDemo2026</p>
        <p><strong>{dc.loginAdmin}:</strong> admin / RalphiAdmin2026</p>
        <Input style={{ marginBottom: 8 }} placeholder={lang === "en" ? "Username" : "Usuario"} value={loginForm.username} onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })} />
        <Input.Password placeholder={lang === "en" ? "Password" : "Contraseña"} value={loginForm.password} onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })} />
      </Modal>
    </div>
  );
}
