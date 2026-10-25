export type ObjectData = Record<string, unknown>;
export const object = (value: unknown): ObjectData => value && typeof value === "object" && !Array.isArray(value) ? value as ObjectData : {};
export const list = (value: unknown): ObjectData[] => Array.isArray(value) ? value.map(object) : [];
export const str = (value: unknown) => value === null || value === undefined ? "—" : String(value);

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T = ObjectData>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path.startsWith("/api/") ? path : `/api/backend${path}`, { ...init, headers, cache: "no-store" });
  if (response.status === 204) return undefined as T;
  const data = await response.json();
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : Array.isArray(data.detail) ? data.detail.map((d: ObjectData) => str(d.msg)).join("; ") : "Ошибка запроса";
    throw new ApiError(response.status, response.status === 501 ? "Эта функция ещё не реализована в backend (501)." : detail);
  }
  return data;
}

export const post = (path: string, body: unknown = {}) => api(path, { method: "POST", body: JSON.stringify(body) });
