import { useRef, useState } from "react";
import { List, useTable } from "@refinedev/antd";
import { AudioOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Form, Input, Modal, Select, Table, message } from "antd";
import { ClientSearchSelect } from "../../components/ClientSearchSelect";
import { useLang, VISIT_TYPES_I18N } from "../../i18n/LangContext";
import { getApiBase } from "../../lib/api";

const API = getApiBase();

export function VisitList() {
  const { lang, pages } = useLang();
  const v = pages.visits;
  const { tableProps, tableQuery } = useTable({ resource: "sop-visits", syncWithLocation: true });
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const [clientId, setClientId] = useState("");
  const [saving, setSaving] = useState(false);
  const [recording, setRecording] = useState(false);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const appendNotes = (t: string) => {
    const cur = form.getFieldValue("notas") || "";
    form.setFieldValue("notas", cur ? `${cur}\n${t}` : t);
  };

  const transcribeToNotes = async (blob: Blob) => {
    const fd = new FormData();
    fd.append("audio_file", blob, "notas.webm");
    const res = await fetch(`${API}/voice/transcribe`, { method: "POST", body: fd });
    const data = await res.json();
    if (data.text) {
      appendNotes(data.text);
      message.success(v.voiceAdded);
    }
  };

  const startRecord = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => e.data.size && chunksRef.current.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        await transcribeToNotes(new Blob(chunksRef.current, { type: "audio/webm" }));
      };
      mediaRef.current = rec;
      rec.start();
      setRecording(true);
    } catch {
      message.error(v.micError);
    }
  };

  const onCreate = async () => {
    if (!clientId) {
      message.error(v.selectClient);
      return;
    }
    const values = await form.validateFields();
    setSaving(true);
    try {
      const res = await fetch(`${API}/sop-visits`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...values, client_id: clientId }),
      });
      if (!res.ok) throw new Error(await res.text());
      message.success(v.created);
      setOpen(false);
      form.resetFields();
      setClientId("");
      tableQuery?.refetch();
    } catch (e) {
      message.error(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <List
      title={v.title}
      headerButtons={
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          {v.create}
        </Button>
      }
    >
      <Table {...tableProps} rowKey="visit_id" scroll={{ x: true }}>
        <Table.Column dataIndex="visit_id" title={v.colId} width={140} />
        <Table.Column dataIndex="client_ruc" title="RUC" />
        <Table.Column dataIndex="client_name" title={v.colClient} />
        <Table.Column dataIndex="tipo" title={v.colType} />
        <Table.Column
          dataIndex="estado"
          title={v.colStatus}
          render={(val, record: Record<string, unknown>) =>
            lang === "en" && record.estado_label ? String(record.estado_label) : String(val ?? "—")
          }
        />
        <Table.Column dataIndex="fecha" title={v.colDate} />
      </Table>

      <Modal title={v.newModal} open={open} onCancel={() => setOpen(false)} onOk={onCreate} confirmLoading={saving} width={640} destroyOnClose>
        <Form form={form} layout="vertical" initialValues={{ tipo: "soporte" }}>
          <Form.Item label={v.clientLabel} required>
            <ClientSearchSelect onSelect={(id) => setClientId(id)} />
          </Form.Item>
          <Form.Item name="tipo" label={v.typeLabel} rules={[{ required: true }]}>
            <Select options={[...VISIT_TYPES_I18N[lang]]} />
          </Form.Item>
          <Form.Item name="notas" label={v.notesLabel}>
            <Input.TextArea rows={5} />
          </Form.Item>
          <Form.Item label={v.voiceLabel}>
            <Button icon={<AudioOutlined />} danger={recording} onClick={recording ? () => { mediaRef.current?.stop(); setRecording(false); } : startRecord}>
              {recording ? v.stopRecord : v.recordNotes}
            </Button>
            <label style={{ marginLeft: 8 }}>
              <input type="file" accept="audio/*" hidden onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) await transcribeToNotes(f);
              }} />
              <Button type="link">{v.uploadAudio}</Button>
            </label>
          </Form.Item>
        </Form>
      </Modal>
    </List>
  );
}
