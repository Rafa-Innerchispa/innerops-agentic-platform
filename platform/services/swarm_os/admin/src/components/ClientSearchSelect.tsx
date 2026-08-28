import { useState } from "react";
import { AutoComplete } from "antd";

const API = import.meta.env.VITE_API_URL || "http://192.168.1.4:8100/api/v1";

export type ClientOption = { client_id: string; name: string; ruc: string; city?: string };

export function ClientSearchSelect({
  onSelect,
  placeholder = "Escribe RUC, cédula o nombre del cliente…",
}: {
  onSelect?: (clientId: string, client: ClientOption) => void;
  placeholder?: string;
}) {
  const [text, setText] = useState("");
  const [options, setOptions] = useState<{ value: string; label: string; client: ClientOption }[]>([]);

  const search = async (q: string) => {
    setText(q);
    if (q.length < 2) {
      setOptions([]);
      return;
    }
    const res = await fetch(`${API}/clients/search?q=${encodeURIComponent(q)}`);
    const json = await res.json();
    setOptions(
      (json.data || []).map((c: ClientOption) => ({
        value: `${c.ruc} — ${c.name}`,
        label: `${c.ruc || "—"} — ${c.name}${c.city ? ` (${c.city})` : ""}`,
        client: c,
      })),
    );
  };

  return (
    <AutoComplete
      style={{ width: "100%" }}
      placeholder={placeholder}
      value={text}
      options={options}
      onSearch={search}
      onChange={setText}
      onSelect={(_val, opt) => {
        const c = (opt as { client: ClientOption }).client;
        setText(`${c.ruc} — ${c.name}`);
        onSelect?.(c.client_id, c);
      }}
      filterOption={false}
      allowClear
    />
  );
}
