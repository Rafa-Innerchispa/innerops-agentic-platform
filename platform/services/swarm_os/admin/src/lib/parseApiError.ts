/** Parsea respuesta HTTP (texto → JSON) y extrae detail de FastAPI. */
export async function parseApiResponse(res: Response): Promise<{ ok: boolean; data: Record<string, unknown>; raw: string }> {
  const raw = await res.text();
  let data: Record<string, unknown> = {};
  try {
    data = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
  } catch {
    /* cuerpo no JSON */
  }
  return { ok: res.ok, data, raw };
}

export function formatApiError(data: Record<string, unknown>, raw: string, status: number): string {
  const detail = data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: string }).msg) : JSON.stringify(d))).join("; ");
  }
  return raw || `HTTP ${status}`;
}
