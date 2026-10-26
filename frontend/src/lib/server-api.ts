import "server-only";
import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

export const apiUrl = process.env.API_URL ?? "http://127.0.0.1:8000/api/v1";

// Отдельная сессия на каждую роль: в одном браузере можно одновременно работать клиентом,
// аналитиком, андеррайтером и администратором (вкладки не вытесняют вход друг друга)
export const roles = ["client", "credit_analyst", "underwriter", "admin"] as const;
export type Role = (typeof roles)[number];
export const sessionCookie = (role: Role) => `credit_session_${role}`;

const firstHeader = (request: NextRequest, name: string) =>
  request.headers.get(name)?.split(",")[0]?.trim() || null;

// Адрес, на который пришёл браузер. В standalone-сборке внутри контейнера request.url
// содержит адрес привязки сервера (http://0.0.0.0:3000), а не хост из адресной строки.
export function requestOrigin(request: NextRequest) {
  const host = firstHeader(request, "x-forwarded-host") ?? firstHeader(request, "host");
  const protocol = firstHeader(request, "x-forwarded-proto") ?? new URL(request.url).protocol.replace(":", "");
  return host ? `${protocol}://${host}` : new URL(request.url).origin;
}

export function sameOrigin(request: NextRequest) {
  return request.headers.get("origin") === requestOrigin(request);
}

// Роль - по странице, с которой пришёл запрос (Referer того же источника): экраны сотрудников
// живут под /staff/<роль> (и старыми адресами A_/U_/AD_), остальное - кабинет клиента
export function requestRole(request: NextRequest): Role {
  let page: URL;
  try { page = new URL(request.headers.get("referer") ?? "", requestOrigin(request)); } catch { return "client"; }
  const path = page.pathname;
  if (path.startsWith("/staff/admin") || path.startsWith("/AD_")) return "admin";
  if (path.startsWith("/staff/underwriter") || path.startsWith("/U_")) return "underwriter";
  if (path.startsWith("/staff/analyst") || path.startsWith("/A_")) return "credit_analyst";
  if (path.startsWith("/staff/login")) {
    const role = page.searchParams.get("role");
    return role === "admin" ? "admin" : role === "underwriter" ? "underwriter" : "credit_analyst";
  }
  return "client";
}

export async function serverApi(request: NextRequest, path: string, init: RequestInit = {}) {
  const token = (await cookies()).get(sessionCookie(requestRole(request)))?.value;
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${apiUrl}${path}`, { ...init, headers, cache: "no-store", signal: AbortSignal.timeout(25_000) });
}
