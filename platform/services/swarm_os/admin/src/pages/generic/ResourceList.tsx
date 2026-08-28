import { useState } from "react";
import { List, useTable } from "@refinedev/antd";
import { Button, Form, Input, InputNumber, Modal, Select, Table, message } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { RESOURCE_CONFIG, type FieldDef } from "../../config/resources";
import { columnTitle, fieldLabel, resourceTitle } from "../../config/resourceI18n";
import { ClientSearchSelect } from "../../components/ClientSearchSelect";
import { useLang } from "../../i18n/LangContext";
import { getApiBase } from "../../lib/api";

const ROUTES: Record<string, string> = {
  entities: "entities",
  clients: "clients",
  "inventory-items": "inventory-items",
  "catalog-products": "catalog-products",
  suppliers: "suppliers",
  quotes: "quotes",
  "sop-visits": "sop-visits",
  "technical-reports": "technical-reports",
};

function fieldInput(f: FieldDef) {
  if (f.type === "number") return <InputNumber style={{ width: "100%" }} />;
  if (f.type === "textarea") return <Input.TextArea rows={4} />;
  if (f.type === "select")
    return <Select options={(f.options || []).map((o) => ({ label: o, value: o }))} />;
  return <Input />;
}

export function ResourceList({ resource }: { resource: string }) {
  const { lang, pages } = useLang();
  const c = pages.common;
  const cfg = RESOURCE_CONFIG[resource];
  const { tableProps, tableQuery } = useTable({ resource, syncWithLocation: true });
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [selectedClient, setSelectedClient] = useState("");
  const API = getApiBase();

  if (!cfg) return <div>{c.unknownResource}: {resource}</div>;

  const title = resourceTitle(lang, resource);

  const onCreate = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const payload = { ...values };
      if (resource === "sop-visits" && selectedClient) {
        payload.client_id = selectedClient;
        delete payload.client_search;
      }
      const path = ROUTES[resource] || resource;
      const res = await fetch(`${API}/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      message.success(c.created);
      setOpen(false);
      form.resetFields();
      setSelectedClient("");
      tableQuery?.refetch();
    } catch (e) {
      message.error(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <List
      title={title}
      headerButtons={
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          {c.create}
        </Button>
      }
    >
      <Table
        {...tableProps}
        rowKey={cfg.idField}
        scroll={{ x: "max-content" }}
        pagination={{ ...tableProps.pagination, showSizeChanger: true, pageSizeOptions: ["10", "25", "50", "100"] }}
      >
        {cfg.columns.map((col) => (
          <Table.Column
            key={col}
            dataIndex={col}
            title={columnTitle(lang, col)}
            ellipsis
            render={(v, record: Record<string, unknown>) => {
              if (col === "estado" && lang === "en" && record.estado_label) {
                return String(record.estado_label);
              }
              return Array.isArray(v) ? v.join(", ") : v != null ? String(v) : "—";
            }}
          />
        ))}
      </Table>

      <Modal
        title={`${c.createTitle} — ${title}`}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={onCreate}
        confirmLoading={saving}
        width={600}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          {resource === "sop-visits" && (
            <Form.Item label={c.clientSearch} required>
              <ClientSearchSelect
                value={selectedClient}
                onChange={(id) => {
                  setSelectedClient(id);
                  form.setFieldValue("client_id", id);
                }}
              />
            </Form.Item>
          )}
          {cfg.fields.map((f) => {
            if (resource === "sop-visits" && f.name === "client_id") return null;
            if (f.name === "code" && resource === "catalog-products") {
              return (
                <Form.Item key={f.name} name={f.name} label={`${fieldLabel(lang, f.name)} (${c.autoCode})`}>
                  <Input placeholder={c.autoCodeHint} />
                </Form.Item>
              );
            }
            return (
              <Form.Item
                key={f.name}
                name={f.name}
                label={fieldLabel(lang, f.name)}
                rules={f.required ? [{ required: true, message: c.required }] : undefined}
                initialValue={f.default}
              >
                {fieldInput(f)}
              </Form.Item>
            );
          })}
        </Form>
      </Modal>
    </List>
  );
}
