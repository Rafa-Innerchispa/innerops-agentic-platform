import { useEffect, useState } from "react";
import { Card, Col, Row, Statistic } from "antd";
import { useLang } from "../../i18n/LangContext";
import { getApiBase } from "../../lib/api";

export function Dashboard() {
  const { pages } = useLang();
  const p = pages.dashboard;
  const [stats, setStats] = useState<Record<string, number>>({});

  useEffect(() => {
    fetch(`${getApiBase()}/stats`)
      .then((r) => r.json())
      .then(setStats)
      .catch(console.error);
  }, []);

  const items = [
    [p.clients, stats.clients],
    [p.inventory, stats.inventory_items],
    [p.catalog, stats.catalog_products],
    [p.suppliers, stats.suppliers],
    [p.quotes, stats.quotes],
    [p.visits, stats.sop_visits],
    [p.reports, stats.technical_reports],
  ];

  return (
    <div>
      <h1>{p.title}</h1>
      <p>{p.server}</p>
      <Row gutter={[16, 16]}>
        {items.map(([label, value]) => (
          <Col key={label as string} xs={24} sm={12} md={8} lg={4}>
            <Card>
              <Statistic title={label as string} value={value ?? 0} />
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}
