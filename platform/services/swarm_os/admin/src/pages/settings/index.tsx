import { useEffect, useState } from "react";
import { Button, Card, Col, ColorPicker, Form, Input, Row, Typography, Upload, message } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import type { UploadRequestOption } from "rc-upload/lib/interface";
import { useLang } from "../../i18n/LangContext";
import { getApiBase, getApiRoot } from "../../lib/api";

const API = getApiBase();

type Company = {
  company_id: string;
  slug: string;
  brand_name: string;
  legal_name: string;
  tagline: string;
  logo_file: string;
  colors: { primary?: string; secondary?: string; accent?: string };
};

export function SettingsPage() {
  const { pages } = useLang();
  const st = pages.settings;
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/companies`);
      const json = await res.json();
      setCompanies(json.data || []);
    } catch {
      message.error(st.loadError);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const save = async (companyId: string, values: Record<string, unknown>) => {
    await fetch(`${API}/companies/${companyId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });
    message.success(st.saved);
    load();
  };

  const seedCatalog = async () => {
    const res = await fetch(`${API}/companies/seed-catalog`, { method: "POST" });
    const json = await res.json();
    message.info(json.message || st.seedDone);
  };

  const uploadLogo = (companyId: string) => async (opt: UploadRequestOption) => {
    const file = opt.file as File;
    const fd = new FormData();
    fd.append("file", file);
    try {
      await fetch(`${API}/companies/${companyId}/logo`, { method: "POST", body: fd });
      message.success(st.logoUpdated);
      load();
      opt.onSuccess?.({});
    } catch (e) {
      opt.onError?.(e as Error);
    }
  };

  const brandingUrl = (file: string) => `${getApiRoot()}/assets/branding/${file}`;

  return (
    <div>
      <Typography.Title level={3}>{st.title}</Typography.Title>
      <Typography.Paragraph type="secondary">{st.intro}</Typography.Paragraph>

      <Button type="primary" onClick={seedCatalog} style={{ marginBottom: 16 }}>
        {st.seedCatalog}
      </Button>

      <Row gutter={[16, 16]}>
        {companies.map((c) => (
          <Col xs={24} lg={12} key={c.company_id}>
            <Card title={c.brand_name} loading={loading}>
              <div style={{ textAlign: "center", marginBottom: 16 }}>
                <img
                  src={brandingUrl(c.logo_file)}
                  alt={c.brand_name}
                  style={{ maxHeight: 64, maxWidth: "100%" }}
                />
              </div>
              <Form
                layout="vertical"
                initialValues={{
                  brand_name: c.brand_name,
                  legal_name: c.legal_name,
                  tagline: c.tagline,
                  primary: c.colors?.primary,
                  secondary: c.colors?.secondary,
                }}
                onFinish={(v) =>
                  save(c.company_id, {
                    brand_name: v.brand_name,
                    legal_name: v.legal_name,
                    tagline: v.tagline,
                    colors: {
                      primary: typeof v.primary === "string" ? v.primary : v.primary?.toHexString?.(),
                      secondary: typeof v.secondary === "string" ? v.secondary : v.secondary?.toHexString?.(),
                    },
                  })
                }
              >
                <Form.Item name="brand_name" label={st.brandName}>
                  <Input />
                </Form.Item>
                <Form.Item name="legal_name" label={st.legalName}>
                  <Input />
                </Form.Item>
                <Form.Item name="tagline" label={st.tagline}>
                  <Input />
                </Form.Item>
                <Form.Item name="primary" label={st.primaryColor}>
                  <ColorPicker format="hex" />
                </Form.Item>
                <Form.Item name="secondary" label={st.secondaryColor}>
                  <ColorPicker format="hex" />
                </Form.Item>
                <Form.Item label={st.changeLogo}>
                  <Upload customRequest={uploadLogo(c.company_id)} showUploadList={false} accept="image/*">
                    <Button icon={<UploadOutlined />}>{st.uploadImage}</Button>
                  </Upload>
                </Form.Item>
                <Button type="primary" htmlType="submit">{st.save}</Button>
              </Form>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}
