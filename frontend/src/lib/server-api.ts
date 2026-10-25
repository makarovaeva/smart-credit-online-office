import "server-only";
import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

export const sessionCookie = "credit_session";
export const apiUrl = process.env.API_URL ?? "http://127.0.0.1:8000/api/v1";

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

export async function serverApi(path: string, init: RequestInit = {}) {
  const token = (await cookies()).get(sessionCookie)?.value;
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${apiUrl}${path}`, { ...init, headers, cache: "no-store", signal: AbortSignal.timeout(25_000) });
}
