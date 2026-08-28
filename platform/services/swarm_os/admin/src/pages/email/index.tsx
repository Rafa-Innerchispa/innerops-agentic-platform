import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { useLang } from "../../i18n/LangContext";
import { getApiBase, getApiRoot } from "../../lib/api";
import {
  CheckCircleOutlined,
  DeleteOutlined,
  LinkOutlined,
  MailOutlined,
  PlusOutlined,
  QrcodeOutlined,
  ReloadOutlined,
  WhatsAppOutlined,
} from "@ant-design/icons";

const API = getApiBase();
const EVO_MANAGER = `${getApiRoot().replace(/:8100$/, "")}:8082/manager`.replace("http://127.0.0.1", "http://192.168.1.4");

type EmailAccount = {
  address: string;
  label: string;
  imap_host: string;
  imap_port: number;
  enabled: boolean;
  monitor_since: string;
  last_uid?: number;
  last_error?: string;
};

type EmailMessage = {
  mail_id: string;
  account_address: string;
  from_addr: string;
  subject: string;
  snippet: string;
  importance: string;
  whatsapp_sent: boolean;
  received_at: string;
  suggested_action?: string;
  route_area?: string;
  route_collection?: string;
  view_url?: string;
  importance_reason?: string;
};

export function EmailMonitorPage() {
  const { pages } = useLang();
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [messages, setMessages] = useState<EmailMessage[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [evoStatus, setEvoStatus] = useState<Record<string, unknown>>({});
  const [apiOk, setApiOk] = useState(true);
  const [open, setOpen] = useState(false);
  const [polling, setPolling] = useState(false);
  const [testingImap, setTestingImap] = useState(false);
  const [qrB64, setQrB64] = useState<string | null>(null);
  const [providerNote, setProviderNote] = useState("");
  const [testingWa, setTestingWa] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [detailMail, setDetailMail] = useState<EmailMessage | null>(null);
  const [form] = Form.useForm();
  const [settingsForm] = Form.useForm();

  type EvoInst = { name: string; connectionStatus?: string; ownerJid?: string };
  const evoInstances: EvoInst[] = (evoStatus.instances as EvoInst[]) || [];

  const fetchJson = async (url: string, init?: RequestInit) => {
    const res = await fetch(url, init);
    if (!res.ok) {
      const t = await res.text();
      throw new Error(res.status === 404 ? `Ruta no encontrada (404) — reinicia swarm-api: sudo systemctl restart swarm-api` : t);
    }
    return res.json();
  };

  const load = async () => {
    try {
      const [a, m, s, st, ev] = await Promise.all([
        fetchJson(`${API}/email/accounts`),
        fetchJson(`${API}/email/messages?limit=40`),
        fetchJson(`${API}/email/settings`),
        fetchJson(`${API}/email/stats`),
        fetchJson(`${API}/email/evolution/status`),
      ]);
      setApiOk(true);
      setAccounts(a.data || []);
      setMessages(m.data || []);
      setStats(st);
      setEvoStatus(ev);
      settingsForm.setFieldsValue({
        evolution_instance: s.evolution_instance || "ralphi-pcdoctor",
        whatsapp_numbers: (s.whatsapp_numbers || []).join(", "),
        keywords_important: (s.keywords_important || []).join(", "),
        notify_on_high: s.notify_on_high ?? true,
      });
    } catch (e) {
      setApiOk(false);
      message.error(String(e));
    }
  };

  useEffect(() => { load(); }, []);

  const openMailDetail = async (mailId: string) => {
    try {
      const doc = await fetchJson(`${API}/email/messages/${mailId}`);
      setDetailMail(doc);
    } catch (e) {
      message.error(String(e));
    }
  };

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const mailId = params.get("mail");
    if (mailId) openMailDetail(mailId);
  }, []);

  const saveSettings = async (v: Record<string, unknown>) => {
    try {
      await fetchJson(`${API}/email/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          evolution_instance: v.evolution_instance,
          whatsapp_numbers: String(v.whatsapp_numbers || "").split(",").map((x) => x.trim()).filter(Boolean),
          keywords_important: String(v.keywords_important || "").split(",").map((x) => x.trim()).filter(Boolean),
          notify_on_high: v.notify_on_high,
        }),
      });
      message.success("Configuración guardada");
      load();
    } catch (e) {
      message.error(String(e));
    }
  };

  const detectProvider = async (email: string) => {
    if (!email.includes("@")) return;
    try {
      const d = await fetchJson(`${API}/email/accounts/detect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address: email }),
      });
      form.setFieldsValue({
        imap_host: d.imap_host,
        imap_port: d.imap_port,
        imap_user: email,
      });
      setProviderNote(`${d.provider}: ${d.auth_note || ""}`);
    } catch {
      /* ignore */
    }
  };

  const testImap = async () => {
    const v = form.getFieldsValue();
    if (!v.imap_host || !v.imap_password) {
      message.warning("Completa correo, servidor y contraseña");
      return;
    }
    setTestingImap(true);
    try {
      const d = await fetchJson(`${API}/email/accounts/test-connection`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          address: v.address,
          imap_host: v.imap_host,
          imap_port: v.imap_port || 993,
          imap_user: v.imap_user || v.address,
          imap_password: v.imap_password,
          imap_folder: v.imap_folder || "INBOX",
        }),
      });
      if (d.ok) message.success(d.message);
      else message.error(d.error + (d.auth_note ? ` — ${d.auth_note}` : ""));
    } catch (e) {
      message.error(String(e));
    } finally {
      setTestingImap(false);
    }
  };

  const createAccount = async () => {
    const v = await form.validateFields();
    const payload = {
      ...v,
      keywords: String(v.keywords || "").split(",").map((x: string) => x.trim()).filter(Boolean),
    };
    try {
      await fetchJson(`${API}/email/accounts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      message.success("Cuenta agregada");
      setOpen(false);
      form.resetFields();
      setProviderNote("");
      load();
    } catch (e) {
      message.error(String(e));
    }
  };

  const createEvoInstance = async () => {
    const name = settingsForm.getFieldValue("evolution_instance") || "ralphi-pcdoctor";
    try {
      const d = await fetchJson(`${API}/email/evolution/create-instance`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instance_name: name }),
      });
      const qr = d.data?.qrcode?.base64;
      if (qr) setQrB64(qr);
      message.success("Instancia creada — escanea el QR con WhatsApp");
      load();
    } catch (e) {
      message.error(String(e));
    }
  };

  const refreshQr = async () => {
    const name = settingsForm.getFieldValue("evolution_instance") || "ralphi-pcdoctor";
    try {
      const d = await fetchJson(`${API}/email/evolution/connect/${name}`);
      const qr = d.data?.base64 || d.data?.qrcode?.base64;
      if (qr) setQrB64(qr);
      else message.info("Si ya escaneaste, el estado debería ser «open»");
    } catch (e) {
      message.error(String(e));
    }
  };

  const testWhatsApp = async () => {
    const num = settingsForm.getFieldValue("whatsapp_numbers")?.split(",")[0]?.trim();
    if (!num) {
      message.error("Pon tu número personal (593…) en Recibir alertas");
      return;
    }
    setTestingWa(true);
    setTestResult(null);
    try {
      const d = await fetchJson(`${API}/email/test-whatsapp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ number: num }),
      });
      setTestResult(JSON.stringify(d, null, 2));
      if (d.status === "sent") message.success("Enviado — revisa tu celular en unos segundos");
      else message.error(d.message || "No se pudo enviar — ver detalle abajo");
    } catch (e) {
      message.error(String(e));
      setTestResult(String(e));
    } finally {
      setTestingWa(false);
    }
  };

  const deleteEvoInstance = async (name: string) => {
    await fetchJson(`${API}/email/evolution/instance/${name}`, { method: "DELETE" });
    message.success(`Instancia ${name} eliminada`);
    load();
  };

  const deleteEmailAccount = async (id: string) => {
    await fetchJson(`${API}/email/accounts/${id}`, { method: "DELETE" });
    message.success("Cuenta correo eliminada");
    load();
  };

  const resyncAccount = async (id: string) => {
    setPolling(true);
    try {
      const d = await fetchJson(`${API}/email/accounts/${id}/resync`, { method: "POST" });
      message.success(`Sincronizados ${d.new} correos nuevos (sin duplicar)`);
      load();
    } catch (e) {
      message.error(String(e));
    } finally {
      setPolling(false);
    }
  };

  const pollNow = async () => {
    setPolling(true);
    try {
      const d = await fetchJson(`${API}/email/poll`, { method: "POST" });
      message.info(`${d.new_messages} nuevos · ${d.alerts_sent} alertas WhatsApp`);
      load();
    } catch (e) {
      message.error(String(e));
    } finally {
      setPolling(false);
    }
  };

  const linkedWa = String(evoStatus.linked_whatsapp || "");
  const connState = evoStatus.connected
    ? "open — conectado ✅"
    : String(
        (evoStatus.connection as { state?: { instance?: { state?: string } } })?.state?.instance?.state || "sin conectar",
      );
  const impColor = (i: string) => (i === "alta" ? "red" : i === "baja" ? "default" : "blue");

  return (
    <div>
      <Typography.Title level={3}><MailOutlined /> {pages.email.title}</Typography.Title>

      {!apiOk && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="API sin rutas de correo (404)"
          description="En el servidor ejecuta: sudo systemctl restart swarm-api && bash scripts/run_admin.sh — luego Ctrl+F5"
        />
      )}

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small">{pages.email.statAccounts}: {stats.accounts ?? 0}</Card></Col>
        <Col span={6}><Card size="small">{pages.email.statActive}: {stats.accounts_enabled ?? 0}</Card></Col>
        <Col span={6}><Card size="small">{pages.email.statStored}: {stats.messages_total ?? 0}</Card></Col>
        <Col span={6}><Card size="small">{pages.email.statHigh}: {stats.messages_high ?? 0}</Card></Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} lg={11}>
          <Card
            title={pages.email.whatsappCard}
            extra={<Tag color={evoStatus.online ? "green" : "red"}>{evoStatus.online ? "Docker OK :8082" : "Offline"}</Tag>}
          >
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="¿Es gratis? ¿Me bloquean?"
              description={
                <>
                  Evolution es <strong>gratis</strong> (open source, en tu servidor). Usa WhatsApp Web no oficial — Meta puede limitar cuentas si envías <strong>spam masivo</strong>.
                  Para <strong>alertas personales</strong> (pocos mensajes a tu número) el riesgo es bajo. Puedes poner <strong>varios números</strong> separados por coma.
                  No uses esto para marketing masivo.
                </>
              }
            />
            <Form form={settingsForm} layout="vertical" onFinish={saveSettings}>
              <Form.Item name="evolution_instance" label="Instancia WhatsApp (selector)" rules={[{ required: true }]}>
                <Select
                  placeholder="Elige instancia conectada"
                  options={evoInstances.map((i) => ({
                    value: i.name,
                    label: `${i.name} — ${i.connectionStatus || "?"} ${i.ownerJid ? `(${i.ownerJid.split("@")[0]})` : ""}`,
                  }))}
                  dropdownRender={(menu) => (
                    <>
                      {menu}
                      <div style={{ padding: 8 }}>
                        <Input
                          placeholder="Nueva instancia…"
                          onPressEnter={(e) => settingsForm.setFieldValue("evolution_instance", (e.target as HTMLInputElement).value)}
                        />
                      </div>
                    </>
                  )}
                />
              </Form.Item>
              {evoInstances.length > 1 && (
                <Space style={{ marginBottom: 8 }}>
                  {evoInstances.filter((i) => i.connectionStatus !== "open").map((i) => (
                    <Popconfirm key={i.name} title={`¿Eliminar instancia ${i.name}?`} onConfirm={() => deleteEvoInstance(i.name)}>
                      <Button size="small" danger icon={<DeleteOutlined />}>Borrar {i.name}</Button>
                    </Popconfirm>
                  ))}
                </Space>
              )}
              <Space wrap style={{ marginBottom: 12 }}>
                <Button icon={<QrcodeOutlined />} onClick={createEvoInstance}>1. Crear instancia + QR</Button>
                <Button onClick={refreshQr}>2. Refrescar QR</Button>
                <a href={EVO_MANAGER} target="_blank" rel="noreferrer">
                  <Button icon={<LinkOutlined />}>Manager Evolution</Button>
                </a>
              </Space>
              {qrB64 && (
                <div style={{ textAlign: "center", marginBottom: 12 }}>
                  <img src={qrB64} alt="QR WhatsApp" style={{ maxWidth: 220 }} />
                  <Typography.Paragraph type="secondary">WhatsApp → Dispositivos vinculados → Vincular</Typography.Paragraph>
                </div>
              )}
              <Typography.Text type="secondary">
                Estado: <Tag color={evoStatus.connected ? "green" : "orange"}>{connState}</Tag>
              </Typography.Text>
              {linkedWa && (
                <Alert
                  type="success"
                  showIcon
                  style={{ marginTop: 8 }}
                  message={`Cuenta WhatsApp del servidor (quien ENVÍA): ${linkedWa}`}
                  description="Es el teléfono con el que escaneaste el QR — puede ser un chip de prueba. No tiene que ser el mismo que recibe alertas."
                />
              )}
              <Alert
                type="info"
                style={{ marginTop: 8, marginBottom: 8 }}
                message="Envía ≠ Recibe"
                description={
                  <>
                    El servidor envía mensajes <strong>desde</strong> la cuenta vinculada (QR) <strong>hacia</strong> los números que pongas abajo.
                    Puedes vincular un WhatsApp de prueba y recibir alertas en <strong>tu celular personal</strong> (otro número).
                  </>
                }
              />
              <Form.Item
                name="whatsapp_numbers"
                label="Tus números para RECIBIR alertas (593…, varios con coma)"
                style={{ marginTop: 12 }}
                extra="Aquí va TU celular personal — no tiene que coincidir con el del QR."
              >
                <Input placeholder="593999059000" />
              </Form.Item>
              <Form.Item name="keywords_important" label="Palabras = correo importante">
                <Input />
              </Form.Item>
              <Form.Item name="notify_on_high" label="Avisar WhatsApp si importante" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Space>
                <Button type="primary" htmlType="submit">Guardar</Button>
                <Button icon={<WhatsAppOutlined />} loading={testingWa} onClick={testWhatsApp}>Probar envío</Button>
              </Space>
              {testResult && (
                <pre style={{ marginTop: 8, fontSize: 11, background: "#f5f5f5", padding: 8, maxHeight: 120, overflow: "auto" }}>
                  {testResult}
                </pre>
              )}
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={13}>
          <Card
            title={pages.email.imapCard}
            extra={
              <Space>
                <Button icon={<ReloadOutlined />} loading={polling} onClick={pollNow}>Revisar</Button>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>Agregar</Button>
              </Space>
            }
          >
            <Table dataSource={accounts} rowKey="email_account_id" size="small" pagination={false}
              columns={[
                { dataIndex: "address", title: "Correo" },
                { dataIndex: "monitor_since", title: "Desde", width: 100 },
                { dataIndex: "last_uid", title: "Últ. UID", width: 80 },
                { dataIndex: "last_error", title: "Estado", render: (e: string) => e ? <Tag color="orange" title={e}>WA/error</Tag> : <Tag color="green">OK</Tag> },
                {
                  title: "Acciones",
                  render: (_: unknown, row: EmailAccount) => (
                    <Space>
                      <Button size="small" onClick={() => resyncAccount(row.email_account_id)}>Sincronizar todo</Button>
                      <Popconfirm title="¿Eliminar esta cuenta?" onConfirm={() => deleteEmailAccount(row.email_account_id)}>
                        <Button size="small" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    </Space>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Alert
        style={{ marginTop: 16 }}
        type="info"
        message="Cómo funciona el correo"
        description={
          <>
            <strong>Guarda</strong> en MongoDB (tabla abajo) todos los correos desde «Monitorear desde» — solo asunto, remitente y resumen (~1 KB c/u, no llena el disco).
            La primera revisión baja hasta <strong>150</strong> correos; pulsa <strong>Revisar</strong> otra vez hasta completar el período.
            <strong>WhatsApp solo</strong> si importancia <Tag color="red">alta</Tag> (pago, factura, urgente…). El resto queda en la tabla sin avisarte.
          </>
        }
      />

      <Card title={pages.email.reviewedCard} style={{ marginTop: 16 }}>
        <Table dataSource={messages} rowKey="mail_id" size="small" scroll={{ x: true }}
          columns={[
            { dataIndex: "received_at", title: "Fecha", width: 160, render: (v: string) => v?.slice(0, 19) },
            { dataIndex: "account_address", title: "Cuenta" },
            { dataIndex: "from_addr", title: "De", ellipsis: true },
            { dataIndex: "subject", title: "Asunto", ellipsis: true },
            { dataIndex: "importance", title: "!", width: 80, render: (v: string) => <Tag color={impColor(v)}>{v}</Tag> },
            { dataIndex: "whatsapp_sent", title: "WA", width: 50, render: (v: boolean) => (v ? "✅" : "—") },
            {
              title: "Ver",
              width: 70,
              render: (_: unknown, row: EmailMessage) => (
                <Button size="small" icon={<LinkOutlined />} onClick={() => openMailDetail(row.mail_id)} />
              ),
            },
          ]}
          onRow={(row) => ({
            onClick: () => openMailDetail(row.mail_id),
            style: { cursor: "pointer" },
          })}
        />
      </Card>

      <Modal
        title="Detalle del correo"
        open={!!detailMail}
        onCancel={() => setDetailMail(null)}
        footer={[
          <Button key="close" onClick={() => setDetailMail(null)}>Cerrar</Button>,
          detailMail?.view_url ? (
            <Button key="link" type="primary" icon={<LinkOutlined />} href={detailMail.view_url} target="_blank" rel="noreferrer">
              Enlace directo
            </Button>
          ) : null,
        ]}
        width={720}
      >
        {detailMail && (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Typography.Text type="secondary">{detailMail.received_at?.slice(0, 19)} · {detailMail.account_address}</Typography.Text>
            <Typography.Title level={5} style={{ margin: 0 }}>{detailMail.subject}</Typography.Title>
            <Typography.Text>De: {detailMail.from_addr}</Typography.Text>
            <Tag color={impColor(detailMail.importance)}>{detailMail.importance}</Tag>
            {detailMail.importance_reason && <Typography.Text type="secondary">Motivo: {detailMail.importance_reason}</Typography.Text>}
            {detailMail.suggested_action && (
              <Alert
                type="info"
                showIcon
                message={`Acción sugerida: ${detailMail.suggested_action.replace(/_/g, " ")}`}
                description={`Área: ${detailMail.route_area || "—"} · Destino futuro: ${detailMail.route_collection || "email_messages"}`}
              />
            )}
            <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{detailMail.snippet}</Typography.Paragraph>
            <Typography.Text copyable={{ text: detailMail.mail_id }}>ID: {detailMail.mail_id}</Typography.Text>
          </Space>
        )}
      </Modal>

      <Modal title={pages.email.addAccount} open={open} onCancel={() => setOpen(false)} onOk={createAccount} width={600}
        footer={[
          <Button key="test" icon={<CheckCircleOutlined />} loading={testingImap} onClick={testImap}>Validar conexión</Button>,
          <Button key="cancel" onClick={() => setOpen(false)}>Cancelar</Button>,
          <Button key="ok" type="primary" onClick={createAccount}>Guardar cuenta</Button>,
        ]}
      >
        <Form form={form} layout="vertical" initialValues={{ imap_port: 993, imap_folder: "INBOX", enabled: true, monitor_since: new Date().toISOString().slice(0, 10) }}>
          <Form.Item name="address" label="Correo" rules={[{ required: true, type: "email" }]}>
            <Input.Search
              placeholder="tu@gmail.com"
              enterButton="Autodetectar servidor"
              onSearch={(v) => detectProvider(v)}
              onBlur={(e) => detectProvider(e.target.value)}
            />
          </Form.Item>
          {providerNote && <Alert type="info" message={providerNote} style={{ marginBottom: 12 }} />}
          <Form.Item name="label" label="Etiqueta"><Input /></Form.Item>
          <Row gutter={8}>
            <Col span={16}>
              <Form.Item name="imap_host" label="Servidor IMAP (auto-detectado)" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="imap_port" label="Puerto"><Input type="number" /></Form.Item>
            </Col>
          </Row>
          <Form.Item name="imap_user" label="Usuario IMAP"><Input placeholder="Igual al correo" /></Form.Item>
          <Form.Item name="imap_password" label="Contraseña / App Password" rules={[{ required: true }]}>
            <Input.Password placeholder="Gmail/Outlook: contraseña de APLICACIÓN, no la normal" />
          </Form.Item>
          <Form.Item name="monitor_since" label="Solo correos desde (ignora PST viejos)" rules={[{ required: true }]}>
            <Input type="date" />
          </Form.Item>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
            <strong>Gmail:</strong> myaccount.google.com/apppasswords ·
            <strong> Outlook/Hotmail:</strong> IMAP activo + app password ·
            <strong> Corporativo:</strong> datos de tu hosting
          </Typography.Paragraph>
        </Form>
      </Modal>
    </div>
  );
}
