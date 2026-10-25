import "server-only";
import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

export const sessionCookie = "credit_session";
export const apiUrl = process.env.API_URL ?? "http://127.0.0.1:8000/api/v1";

export function sameOrigin(request: NextRequest) {
  return request.headers.get("origin") === new URL(request.url).origin;
}

export async function serverApi(path: string, init: RequestInit = {}) {
  const token = (await cookies()).get(sessionCookie)?.value;
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${apiUrl}${path}`, { ...init, headers, cache: "no-store", signal: AbortSignal.timeout(25_000) });
}
