import { useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Form,
  Input,
  List,
  Modal,
  Select,
  Space,
  Spin,
  Steps,
  Tag,
  Typography,
  message,
} from "antd";
import { MailOutlined, ReloadOutlined, SearchOutlined, SendOutlined } from "@ant-design/icons";
import { getApiBase } from "../lib/api";

export type GuidedTourPayload = {
  voice_text: string;
  client_ruc: string;
  client_name: string;
  client_phone: string;
  client_address: string;
  product_codes: string[];
  company_id: string;
  check_email: boolean;
  email_mail_id?: string;
};

type CatalogItem = {
  code: string;
  nombre: string;
  tipo?: string;
  precio_sugerido?: number;
};

type EmailParsed = {
  summary?: string;
  ruc?: string;
  client_hint?: string;
  phone?: string;
  products_hint?: string[];
  is_quote_request?: boolean;
  is_automated_sender?: boolean;
  quote_keyword_hits?: number;
};

type ExistingClient = {
  client_id?: string;
  name?: string;
  ruc?: string;
  phone?: string;
};

type EmailCandidate = {
  email?: { mail_id?: string; subject?: string; from_addr?: string; snippet?: string; importance?: string };
  parsed?: EmailParsed;
  score?: number;
  already_processed?: boolean;
  existing_client?: ExistingClient | null;
};

type PrepData = {
  catalog: CatalogItem[];
  email_candidates?: EmailCandidate[];
  email_alert?: EmailCandidate;
  evolution_active?: string;
  evolution_note?: string;
};

type Props = {
  open: boolean;
  onClose: () => void;
  onRun: (payload: GuidedTourPayload) => void;
  loading?: boolean;
};

export function DemoWizard({ open, onClose, onRun, loading }: Props) {
  const [step, setStep] = useState(0);
  const [prep, setPrep] = useState<PrepData | null>(null);
  const [candidates, setCandidates] = useState<EmailCandidate[]>([]);
  const [selectedMailId, setSelectedMailId] = useState<string | null>(null);
  const [skipEmail, setSkipEmail] = useState(false);
  const [checkingMail, setCheckingMail] = useState(false);
  const [sendingDemo, setSendingDemo] = useState<string | null>(null);
  const [form] = Form.useForm();
  const API = getApiBase();

  const selectedCandidate = candidates.find((c) => c.email?.mail_id === selectedMailId) || null;

  const applyCandidateToForm = (alert: EmailCandidate, catalog: CatalogItem[], data?: { voice_text?: string }) => {
    const p = alert.parsed || {};
    const e = alert.email || {};
    const codes = (p.products_hint || []).filter((c) => catalog.some((x) => x.code === c));
    const patch: Record<string, unknown> = {
      email_mail_id: e.mail_id,
    };
    if (p.ruc) patch.client_ruc = p.ruc;
    if (p.client_hint) patch.client_name = p.client_hint;
    if (p.phone) patch.client_phone = p.phone;
    if (data?.voice_text) patch.voice_text = data.voice_text;
    if (codes.length) patch.product_codes = codes;
    form.setFieldsValue(patch);
  };

  const selectCandidate = (alert: EmailCandidate, catalog: CatalogItem[], data?: { voice_text?: string }) => {
    const mailId = alert.email?.mail_id;
    if (!mailId) return;
    setSelectedMailId(mailId);
    setSkipEmail(false);
    applyCandidateToForm(alert, catalog, data);
  };

  const loadPrep = async (): Promise<PrepData | null> => {
    try {
      const r = await fetch(`${API}/hackathon/demo/prep`);
      const d = (await r.json()) as PrepData;
      setPrep(d);
      return d;
    } catch {
      message.error("Could not load demo options");
      return null;
    }
  };

  const applyCheckEmailResponse = (data: Record<string, unknown>, catalog: CatalogItem[]) => {
    const list = (data.candidates as EmailCandidate[]) || [];
    setCandidates(list);

    if (list.length === 0) {
      setSelectedMailId(null);
      form.setFieldValue("email_mail_id", undefined);
      return;
    }

    const primary = list[0];
    selectCandidate(primary, catalog, { voice_text: data.voice_text as string | undefined });
  };

  const checkMail = async (poll = true, catalogOverride?: CatalogItem[]) => {
    setCheckingMail(true);
    try {
      const res = await fetch(`${API}/hackathon/demo/check-email?poll=${poll}`, {
        method: "POST",
      });
      const data = await res.json();
      const cat = catalogOverride || prep?.catalog || [];

      if (!data.ok) {
        setCandidates([]);
        setSelectedMailId(null);
        form.setFieldValue("email_mail_id", undefined);
        message.warning(
          data.message ||
            "No se encontró correo de cotización. Usa Send demo, envía un email con RUC, o continúa sin correo.",
        );
        return;
      }

      applyCheckEmailResponse(data, cat);
      const primary = (data.candidates as EmailCandidate[])?.[0] || null;
      if (primary?.already_processed) {
        message.warning(data.alert_message || "Correo ya procesado — cliente ya existe");
      } else {
        message.success(data.alert_message || `${(data.candidates as EmailCandidate[])?.length || 1} candidato(s) encontrado(s)`);
      }
    } catch {
      message.error("Mail check failed");
    } finally {
      setCheckingMail(false);
    }
  };

  const sendDemoEmail = async (scenario: "new_client" | "existing_client") => {
    setSendingDemo(scenario);
    try {
      const res = await fetch(`${API}/hackathon/demo/send-test-email`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || data.message || `HTTP ${res.status}`);
      }
      const cat = prep?.catalog || [];
      if (data.candidates?.length) {
        applyCheckEmailResponse(data, cat);
        message.success(data.message || "Correo demo enviado — selecciona en la lista");
      } else {
        message.info("Correo enviado — pulsa Refresh mail si aún no aparece");
        await checkMail(true, cat);
      }
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "Send demo failed");
    } finally {
      setSendingDemo(null);
    }
  };

  useEffect(() => {
    if (!open) return;
    setStep(0);
    setCandidates([]);
    setSelectedMailId(null);
    setSkipEmail(false);
    form.resetFields();
    form.setFieldsValue({
      company_id: "pcdoctor",
      product_codes: [],
    });
    void (async () => {
      const d = await loadPrep();
      const cat = d?.catalog || [];
      if (d?.email_candidates?.length) {
        setCandidates(d.email_candidates);
        selectCandidate(d.email_candidates[0], cat);
      } else {
        await checkMail(true, cat);
      }
    })();
  }, [open]);

  const lookupSri = async () => {
    const ruc = form.getFieldValue("client_ruc");
    if (!ruc || String(ruc).length < 10) {
      message.warning("Enter tax ID first (from email or manual)");
      return;
    }
    const res = await fetch(`${API}/ruc/lookup?id=${encodeURIComponent(ruc)}`);
    const data = await res.json();
    if (!res.ok) {
      message.error(data.detail || "SRI lookup failed");
      return;
    }
    const r = data.result || {};
    if (r.name) {
      form.setFieldsValue({
        client_name: r.name || r.trade_name,
        client_address: r.address || form.getFieldValue("client_address"),
      });
      message.success("SRI validated — company loaded");
    } else {
      message.warning("Not found in SRI — enter name manually");
    }
  };

  const continueWithoutEmail = () => {
    setSkipEmail(true);
    setSelectedMailId(null);
    form.setFieldValue("email_mail_id", undefined);
    setStep(1);
  };

  const goNext = () => {
    if (step === 0 && !skipEmail && selectedCandidate?.parsed?.ruc) {
      form.setFieldValue("client_ruc", selectedCandidate.parsed.ruc);
    }
    setStep((s) => s + 1);
  };

  const finish = async () => {
    try {
      await form.validateFields();
    } catch {
      message.error("Completa RUC/cédula (10+ dígitos), nombre y WhatsApp");
      return;
    }
    const v = form.getFieldsValue();
    const ruc = String(v.client_ruc || "").trim();
    if (ruc.length < 10) {
      message.error("RUC o cédula obligatorio (mínimo 10 dígitos)");
      return;
    }
    onRun({
      voice_text: v.voice_text || `Quote for ${v.client_name}`,
      client_ruc: ruc,
      client_name: v.client_name || "",
      client_phone: v.client_phone || "",
      client_address: v.client_address || "",
      product_codes: v.product_codes || [],
      company_id: v.company_id || "pcdoctor",
      check_email: !skipEmail && Boolean(v.email_mail_id || selectedMailId),
      email_mail_id: skipEmail ? undefined : v.email_mail_id || selectedMailId || undefined,
    });
  };

  const catalog = prep?.catalog || [];
  const parsed = selectedCandidate?.parsed;
  const alreadyProcessed = selectedCandidate?.already_processed;
  const existingClient = selectedCandidate?.existing_client;

  return (
    <Modal
      title="Guided demo — email → client → quote"
      open={open}
      onCancel={onClose}
      width={760}
      footer={
        <Space>
          <Button onClick={onClose}>Cancel</Button>
          {step > 0 && <Button onClick={() => setStep((s) => s - 1)}>Back</Button>}
          {step < 3 ? (
            <Button type="primary" onClick={goNext}>
              Next
            </Button>
          ) : (
            <Button type="primary" loading={loading} onClick={finish}>
              Run mission
            </Button>
          )}
        </Space>
      }
      destroyOnClose={false}
    >
      <Steps
        size="small"
        current={step}
        style={{ marginBottom: 20 }}
        items={[
          { title: "Email alert" },
          { title: "Client + SRI" },
          { title: "Products" },
          { title: "Confirm" },
        ]}
      />

      <Form form={form} layout="vertical">
        <Form.Item name="email_mail_id" hidden>
          <Input />
        </Form.Item>

        {step === 0 && (
          <>
            <Spin spinning={checkingMail}>
              {candidates.length === 0 && !checkingMail ? (
                <Alert
                  type="info"
                  showIcon
                  icon={<MailOutlined />}
                  message="Sin candidatos de cotización"
                  description="Envía un correo con RUC y palabras como «cotización», usa los botones Send demo, o continúa sin correo para ingresar el RUC manualmente."
                  style={{ marginBottom: 12 }}
                />
              ) : (
                <List
                  size="small"
                  header={
                    <Typography.Text strong>
                      Candidatos de cotización ({candidates.length}) — selecciona uno
                    </Typography.Text>
                  }
                  dataSource={candidates}
                  style={{ marginBottom: 12, border: "1px solid #334155", borderRadius: 8 }}
                  renderItem={(item) => {
                    const mail = item.email;
                    const p = item.parsed;
                    const mailId = mail?.mail_id || "";
                    const isSelected = mailId === selectedMailId;
                    return (
                      <List.Item
                        style={{
                          cursor: "pointer",
                          background: isSelected ? "rgba(34,211,238,0.12)" : undefined,
                          borderLeft: isSelected ? "3px solid #22d3ee" : "3px solid transparent",
                          padding: "10px 12px",
                        }}
                        onClick={() => selectCandidate(item, catalog)}
                      >
                        <List.Item.Meta
                          title={
                            <Space wrap>
                              <span>{mail?.subject || "(sin asunto)"}</span>
                              {item.already_processed ? (
                                <Badge status="warning" text="Procesado" />
                              ) : (
                                <Badge status="success" text="Nuevo" />
                              )}
                              {typeof item.score === "number" && (
                                <Tag color="blue">score {item.score}</Tag>
                              )}
                            </Space>
                          }
                          description={
                            <div style={{ fontSize: 12 }}>
                              <div>
                                <strong>From:</strong> {mail?.from_addr}
                              </div>
                              {p?.ruc && (
                                <div style={{ color: "#16a34a", fontWeight: 600 }}>RUC: {p.ruc}</div>
                              )}
                              {p?.summary && <div style={{ color: "#94a3b8" }}>{p.summary}</div>}
                              {item.existing_client?.name && (
                                <div style={{ color: "#ca8a04" }}>Cliente existente: {item.existing_client.name}</div>
                              )}
                            </div>
                          }
                        />
                      </List.Item>
                    );
                  }}
                />
              )}

              {selectedCandidate?.email && (
                <Alert
                  type={alreadyProcessed ? "warning" : parsed?.is_quote_request ? "success" : "info"}
                  showIcon
                  icon={<MailOutlined />}
                  message={
                    skipEmail
                      ? "Continuarás sin correo — RUC manual en el siguiente paso"
                      : alreadyProcessed
                        ? `Seleccionado (procesado): ${existingClient?.name || "cliente existente"}`
                        : parsed?.summary || "Correo seleccionado"
                  }
                  description={
                    !skipEmail && selectedCandidate.email ? (
                      <div style={{ marginTop: 8, fontSize: 12, whiteSpace: "pre-wrap" }}>
                        {selectedCandidate.email.snippet}
                      </div>
                    ) : null
                  }
                  style={{ marginBottom: 12 }}
                />
              )}
            </Spin>

            <Space wrap style={{ marginBottom: 8 }}>
              <Button icon={<ReloadOutlined />} loading={checkingMail} onClick={() => checkMail(true)}>
                Refresh mail (poll IMAP)
              </Button>
              <Button
                icon={<SendOutlined />}
                loading={sendingDemo === "new_client"}
                onClick={() => sendDemoEmail("new_client")}
              >
                Send demo: NEW client
              </Button>
              <Button
                icon={<SendOutlined />}
                loading={sendingDemo === "existing_client"}
                onClick={() => sendDemoEmail("existing_client")}
              >
                Send demo: EXISTING client
              </Button>
              <Button type="default" onClick={continueWithoutEmail}>
                Continue without email
              </Button>
            </Space>

            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
              Send demo envía un correo real vía SMTP al buzón configurado. Tras poll IMAP aparece en la lista para que
              elijas el candidato. Se excluyen remitentes automáticos (SRI, noreply, comprobantes@, etc.).
            </Typography.Paragraph>
            <Typography.Paragraph type="secondary" style={{ fontSize: 11 }}>
              Plantilla NEW client: empresa ficticia + RUC nuevo 13 dígitos + solicitud de cotización (switch PoE,
              cámaras, cableado).
            </Typography.Paragraph>
          </>
        )}

        {step === 1 && (
          <>
            {skipEmail && (
              <Alert
                type="info"
                showIcon
                message="Modo manual — sin correo seleccionado"
                description="Ingresa RUC y datos del cliente; la misión continuará normalmente."
                style={{ marginBottom: 12 }}
              />
            )}
            {parsed?.ruc && !skipEmail && (
              <Alert type="success" showIcon message={`RUC from email: ${parsed.ruc}`} style={{ marginBottom: 12 }} />
            )}
            {alreadyProcessed && existingClient?.name && (
              <Alert
                type="warning"
                showIcon
                message={`Cliente ya existe: ${existingClient.name}`}
                style={{ marginBottom: 12 }}
              />
            )}
            <Form.Item name="client_ruc" label="Tax ID (RUC / cédula)" rules={[{ required: true, min: 10 }]}>
              <Space.Compact style={{ width: "100%" }}>
                <Input placeholder="RUC o cédula del correo" style={{ width: "calc(100% - 130px)" }} />
                <Button type="primary" icon={<SearchOutlined />} onClick={lookupSri}>
                  SRI lookup
                </Button>
              </Space.Compact>
            </Form.Item>
            <Form.Item name="client_name" label="Client / company name" rules={[{ required: true }]}>
              <Input placeholder="From SRI or email" />
            </Form.Item>
            <Form.Item name="client_phone" label="WhatsApp (E.164)" rules={[{ required: true }]}>
              <Input placeholder="593XXXXXXXXX" />
            </Form.Item>
            <Form.Item name="client_address" label="Site address">
              <Input placeholder="From SRI address" />
            </Form.Item>
            <Form.Item name="company_id" label="Billing company">
              <Select
                options={[
                  { value: "pcdoctor", label: "PC Doctor S.A." },
                  { value: "innerchispa", label: "InnerChispa" },
                ]}
              />
            </Form.Item>
          </>
        )}

        {step === 2 && (
          <>
            <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
              Catalog — products & services (DB13). Lines are saved to MongoDB quote.
            </Typography.Paragraph>
            <Form.Item name="product_codes" label="Items to quote" rules={[{ required: true }]}>
              <Checkbox.Group style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {catalog.map((p) => (
                  <Checkbox key={p.code} value={p.code}>
                    <strong>{p.code}</strong> — {p.nombre}{" "}
                    <Typography.Text type="secondary">
                      ({p.tipo || "item"}) ${p.precio_sugerido ?? "—"}
                    </Typography.Text>
                  </Checkbox>
                ))}
              </Checkbox.Group>
            </Form.Item>
            <Form.Item name="voice_text" label="Technician / email summary">
              <Input.TextArea rows={2} />
            </Form.Item>
          </>
        )}

        {step === 3 && (
          <Alert
            type="success"
            message="Ready — 8 agents will run in the Mission Log"
            description={
              <>
                Client: <strong>{form.getFieldValue("client_name")}</strong> · RUC:{" "}
                {form.getFieldValue("client_ruc")} · WhatsApp: {form.getFieldValue("client_phone")}
                <br />
                Items: {(form.getFieldValue("product_codes") || []).join(", ")}
                <br />
                Email:{" "}
                {skipEmail
                  ? "— (manual entry)"
                  : selectedCandidate?.email?.subject || form.getFieldValue("email_mail_id") || "—"}
                <br />
                WhatsApp instance: {prep?.evolution_active || "auto"} ({prep?.evolution_note})
                <br />
                <Typography.Text type="secondary">
                  Al ejecutar, la cotización se guardará en MongoDB (<code>quotes</code>) con serial PCD-COT-*, total
                  calculado e ID verificable en el resumen de misión.
                </Typography.Text>
                {alreadyProcessed && (
                  <>
                    <br />
                    <Typography.Text type="warning">
                      Nota: correo ya procesado — la misión reutilizará cliente existente sin duplicar cotización.
                    </Typography.Text>
                  </>
                )}
              </>
            }
          />
        )}
      </Form>
    </Modal>
  );
}
