import { useTable } from "@refinedev/antd";
import { Table } from "antd";

export function GenericList({ resource, title }: { resource: string; title: string }) {
  const { tableProps } = useTable({ resource, syncWithLocation: true });
  return (
    <div style={{ padding: 24 }}>
      <h2>{title}</h2>
      <Table
        {...tableProps}
        rowKey={(r: Record<string, string>) =>
          r.client_id ||
          r.item_code ||
          r.code ||
          r.supplier_id ||
          r.quote_id ||
          r.visit_id ||
          JSON.stringify(r)
        }
        scroll={{ x: true }}
      />
    </div>
  );
}
