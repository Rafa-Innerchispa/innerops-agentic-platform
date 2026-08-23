import type { BaseRecord, DataProvider } from "@refinedev/core";
import { getApiBase } from "../lib/api";

const API = getApiBase();

/** Mapeo recurso Refine → endpoint FastAPI */
const routes: Record<string, string> = {
  entities: "entities",
  clients: "clients",
  "inventory-items": "inventory-items",
  "catalog-products": "catalog-products",
  suppliers: "suppliers",
  quotes: "quotes",
  "sop-visits": "sop-visits",
  "technical-reports": "technical-reports",
};

async function http<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<T>;
}

export const dataProvider: DataProvider = {
  getList: async ({ resource, pagination }) => {
    const path = routes[resource] || resource;
    const page = pagination?.current ?? 1;
    const pageSize = pagination?.pageSize ?? 25;
    const skip = (page - 1) * pageSize;
    const json = await http<{ data: BaseRecord[]; total: number }>(
      `${API}/${path}?skip=${skip}&limit=${pageSize}`,
    );
    return { data: json.data as BaseRecord[], total: json.total };
  },

  getOne: async ({ resource, id }) => {
    const path = routes[resource] || resource;
    const data = await http<BaseRecord>(`${API}/${path}/${id}`);
    return { data };
  },

  create: async ({ resource, variables }) => {
    const path = routes[resource] || resource;
    const data = await http<BaseRecord>(`${API}/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(variables),
    });
    return { data };
  },

  update: async ({ resource, id, variables }) => {
    const path = routes[resource] || resource;
    const data = await http<BaseRecord>(`${API}/${path}/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(variables),
    });
    return { data };
  },

  deleteOne: async () => {
    throw new Error("delete deshabilitado en MVP");
  },

  getApiUrl: () => API,
} as DataProvider;
