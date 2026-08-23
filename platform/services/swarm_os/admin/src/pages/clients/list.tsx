import { useState } from "react";
import { List, useTable } from "@refinedev/antd";
import { Button, Form, Input, Modal, Select, Space, Table, message } from "antd";
import { PlusOutlined, SearchOutlined } from "@ant-design/icons";
import { useLang } from "../../i18n/LangContext";
import { getApiBase } from "../../lib/api";

const API = getApiBase();

const PAISES = ["Ecuador", "Colombia", "Perú", "Estados Unidos", "España"];
const CIUDADES_EC = [
  "Guayaquil", "Quito", "Cuenca", "Manta", "Ambato", "Machala", "Portoviejo", "Loja", "Riobamba", "Esmeraldas",
];

export function ClientList() {
  const { pages } = useLang();
  const cl = pages.clients;
  const { tableProps, tableQuery } = useTable({ resource: "clients", syncWithLocation: true });
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [lookupLoading, setLookupLoading] = useState(false);

  const lookupSri = async () => {
    const ruc = form.getFieldValue("ruc");
    if (!ruc || String(ruc).length < 10) {
      message.warning(cl.rucWarn);
      return;
    }
    setLookupLoading(true);
    try {
      const res = await fetch(`${API}/ruc/lookup?id=${encodeURIComponent(ruc)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "SRI error");
      if (!data.duplicate?.passed) {
        message.error(data.duplicate?.message || cl.sriDup);
        return;
      }
      const r = data.result || {};
      if (r.status === "NO_ENCONTRADO" || r.status === "ID_INVALIDO") {
        message.warning(r.error || cl.sriNotFound);
        return;
      }
      form.setFieldsValue({
        name: r.name || r.trade_name || form.getFieldValue("name"),
        address: r.address || form.getFieldValue("address"),
        city: r.city || form.getFieldValue("city"),
        ruc: r.ruc || ruc,
      });
      message.success(cl.sriLoaded);
    } catch (e) {
      message.error(String(e));
    } finally {
      setLookupLoading(false);
    }
  };

  const onCreate = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const res = await fetch(`${API}/clients`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!res.ok) throw new Error(await res.text());
      message.success(cl.created);
      setOpen(false);
      form.resetFields();
      tableQuery?.refetch();
    } catch (e) {
      message.error(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <List
      title={cl.title}
      headerButtons={
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          {cl.create}
        </Button>
      }
    >
      <Table {...tableProps} rowKey="client_id" scroll={{ x: 1200 }}>
        <Table.Column dataIndex="ruc" title={cl.colRuc} fixed="left" />
        <Table.Column dataIndex="name" title={cl.colName} />
        <Table.Column dataIndex="estado" title={cl.colType} />
        <Table.Column dataIndex="city" title={cl.colCity} />
        <Table.Column dataIndex="pais" title={cl.colCountry} />
        <Table.Column dataIndex="phone" title={cl.colPhone} />
        <Table.Column dataIndex="email" title={cl.colEmail} />
      </Table>

      <Modal title={cl.createModal} open={open} onCancel={() => setOpen(false)} onOk={onCreate} confirmLoading={saving} width={640}>
        <Form form={form} layout="vertical" initialValues={{ pais: "Ecuador", estado: "Cliente" }}>
          <Form.Item
            name="ruc"
            label={cl.rucLabel}
            rules={[{ required: true, message: cl.rucRequired }, { min: 10, message: cl.rucMin }]}
          >
            <Space.Compact style={{ width: "100%" }}>
              <Input placeholder={cl.rucPlaceholder} style={{ width: "calc(100% - 120px)" }} />
              <Button icon={<SearchOutlined />} loading={lookupLoading} onClick={lookupSri}>
                {cl.lookupSri}
              </Button>
            </Space.Compact>
          </Form.Item>
          <Form.Item name="name" label={cl.nameLabel} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="estado" label={cl.typeLabel} rules={[{ required: true }]}>
            <Select options={[
              { value: "Cliente", label: "Cliente" },
              { value: "Proveedor", label: "Proveedor" },
              { value: "Cliente y Proveedor", label: "Cliente y Proveedor" },
            ]} />
          </Form.Item>
          <Form.Item name="entidades" label={cl.entitiesLabel}>
            <Select mode="tags" placeholder={cl.entitiesPlaceholder} />
          </Form.Item>
          <Form.Item name="pais" label={cl.countryLabel} rules={[{ required: true }]}>
            <Select showSearch options={PAISES.map((p) => ({ value: p, label: p }))} />
          </Form.Item>
          <Form.Item name="city" label={cl.cityLabel} rules={[{ required: true }]}>
            <Select showSearch options={CIUDADES_EC.map((c) => ({ value: c, label: c }))} />
          </Form.Item>
          <Form.Item name="address" label={cl.addressLabel}>
            <Input />
          </Form.Item>
          <Form.Item
            name="phone"
            label={cl.phoneLabel}
            rules={[{ pattern: /^\+593\d{9}$/, message: cl.phonePattern }]}
          >
            <Input placeholder="+593999059000" />
          </Form.Item>
          <Form.Item
            name="email"
            label={cl.emailLabel}
            rules={[{ type: "email", message: cl.emailInvalid }]}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </List>
  );
}
