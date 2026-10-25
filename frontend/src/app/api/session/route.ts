import { NextRequest, NextResponse } from "next/server";
import { apiUrl, sameOrigin, serverApi, sessionCookie } from "@/lib/server-api";

export async function GET() {
  try {
    const response = await serverApi("/me");
    return NextResponse.json(await response.json(), { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ detail: "Backend недоступен" }, { status: 503 }); }
}

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) return NextResponse.json({ detail: "Недопустимый источник запроса" }, { status: 403 });
  let body;
  try { body = await request.json(); } catch { return NextResponse.json({ detail: "Некорректный JSON" }, { status: 400 }); }
  const client = body?.kind === "client";
  if (client ? typeof body.phone !== "string" : typeof body?.email !== "string" || typeof body?.password !== "string") {
    return NextResponse.json({ detail: "Заполните данные входа" }, { status: 422 });
  }
  try {
    const response = await fetch(`${apiUrl}/auth/login${client ? "/phone" : ""}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store",
      body: JSON.stringify(client ? { phone: body.phone } : { email: body.email, password: body.password }),
      signal: AbortSignal.timeout(25_000),
    });
    const data = await response.json();
    if (!response.ok) return NextResponse.json(data, { status: response.status });
    const result = NextResponse.json({ ok: true });
    result.cookies.set(sessionCookie, data.access_token, { httpOnly: true, sameSite: "lax", path: "/", maxAge: data.expires_in, secure: new URL(request.url).protocol === "https:" });
    return result;
  } catch { return NextResponse.json({ detail: "Backend недоступен" }, { status: 503 }); }
}

export async function DELETE(request: NextRequest) {
  if (!sameOrigin(request)) return NextResponse.json({ detail: "Недопустимый источник запроса" }, { status: 403 });
  const response = NextResponse.json({ ok: true });
  response.cookies.set(sessionCookie, "", { httpOnly: true, sameSite: "lax", path: "/", maxAge: 0 });
  return response;
}
