/** API base: usa proxy Vite (mismo origen) para que ngrok y LAN funcionen sin CORS. */
export function getApiBase(): string {
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL.replace(/\/$/, "");
  }
  if (typeof window !== "undefined") {
    return `${window.location.origin}/api/v1`;
  }
  return "http://127.0.0.1:8100/api/v1";
}

export function getApiRoot(): string {
  return getApiBase().replace(/\/api\/v1\/?$/, "");
}
