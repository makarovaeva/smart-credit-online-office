import { NextRequest, NextResponse } from "next/server";
import { sameOrigin, serverApi } from "@/lib/server-api";

type Context = { params: Promise<{ path: string[] }> };
async function proxy(request: NextRequest, context: Context) {
  const { path } = await context.params;
  if (!path.length || !["me", "products", "companies", "applications", "backoffice", "loans", "notifications"].includes(path[0]) || path.some(p => !/^[a-zA-Z0-9_-]+$/.test(p))) {
    return NextResponse.json({ detail: "Неизвестный API-метод" }, { status: 404 });
  }
  if (request.method !== "GET" && !sameOrigin(request)) return NextResponse.json({ detail: "Недопустимый источник запроса" }, { status: 403 });
  try {
    const headers = new Headers();
    const contentType = request.headers.get("content-type");
    if (contentType) headers.set("Content-Type", contentType);
    const upstream = await serverApi(`/${path.join("/")}${new URL(request.url).search}`, {
      method: request.method, headers,
      body: request.method === "GET" ? undefined : await request.arrayBuffer(),
    });
    const outgoing = new Headers({ "Cache-Control": "no-store" });
    for (const name of ["content-type", "content-disposition"]) {
      const value = upstream.headers.get(name);
      if (value) outgoing.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: outgoing });
  } catch { return NextResponse.json({ detail: "Не удалось связаться с backend. Повторите запрос." }, { status: 503 }); }
}
export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
