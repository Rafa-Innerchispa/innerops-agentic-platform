import { useState } from "react";
import { List, useTable } from "@refinedev/antd";
import { PlusOutlined } from "@ant-design/icons";
import { Button, Form, Input, Modal, Select, Table, message } from "antd";
import { ClientSearchSelect, type ClientOption } from "../../components/ClientSearchSelect";
import { useLang } from "../../i18n/LangContext";
import { getApiBase } from "../../lib/api";

const API = getApiBase();

type VisitRow = { visit_id: string; tipo: string; fecha: string; estado: string; notas?: string };

export function ReportList() {
  const { lang, pages } = useLang();
  const rp = pages.reports;
  const { tableProps, tableQuery } = useTable({ resource: "technical-reports", syncWithLocation: true });
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const [visits, setVisits] = useState<VisitRow[]>([]);
  const [saving, setSaving] = useState(false);

  const loadVisits = async (clientId: string) => {
    const res = await fetch(`${API}/sop-visits/by-client/${clientId}`);
    const json = await res.json();
    setVisits(json.data || []);
  };

  const onCreate = async () => {
    const values = await form.validateFields();
    if (!values.visit_id) {
      message.error(rp.selectVisit);
      return;
    }
    setSaving(true);
    try {
      const res = await fetch(`${API}/technical-reports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!res.ok) throw new Error(await res.text());
      message.success(rp.created);
      setOpen(false);
      form.resetFields();
      setVisits([]);
      tableQuery?.refetch();
    } catch (e) {
      message.error(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <List
      title={rp.title}
      headerButtons={
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          {rp.create}
        </Button>
      }
    >
      <Table {...tableProps} rowKey="report_id" scroll={{ x: true }}>
        <Table.Column dataIndex="serial" title="#" />
        <Table.Column dataIndex="titulo" title={rp.colTitle} />
        <Table.Column dataIndex="client_ruc" title={rp.colRuc} />
        <Table.Column dataIndex="client_name" title={rp.colClient} />
        <Table.Column dataIndex="visit_id" title={rp.colVisit} width={140} />
        <Table.Column
          dataIndex="estado"
          title={rp.colStatus}
          render={(v, record: Record<string, unknown>) =>
            lang === "en" && record.estado_label ? String(record.estado_label) : String(v ?? "—")
          }
        />
      </Table>

      <Modal title={rp.newModal} open={open} onCancel={() => setOpen(false)} onOk={onCreate} confirmLoading={saving} width={640} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item label={rp.clientStep} required>
            <ClientSearchSelect
              onSelect={(id, c?: ClientOption) => {
                form.setFieldValue("client_id", id);
                loadVisits(id);
                if (c) form.setFieldValue("titulo", `Informe técnico — ${c.name}`);
              }}
            />
          </Form.Item>
          <Form.Item name="visit_id" label={rp.visitStep} rules={[{ required: true }]}>
            <Select
              placeholder={visits.length ? rp.visitPlaceholder : rp.visitFirst}
              options={visits.map((v) => ({
                value: v.visit_id,
                label: `${v.tipo} — ${v.fecha?.slice(0, 10) || ""} — ${v.notas?.slice(0, 40) || v.visit_id}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="titulo" label={rp.titleLabel} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="content_md" label={rp.contentLabel}>
            <Input.TextArea rows={6} placeholder={rp.contentPlaceholder} />
          </Form.Item>
          <p style={{ color: "#888", fontSize: 12 }}>{rp.autoSerial}</p>
        </Form>
      </Modal>
    </List>
  );
}
