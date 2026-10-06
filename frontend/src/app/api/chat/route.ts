import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const BACKEND_BASE_URL = process.env.BACKEND_BASE_URL ?? "http://localhost:8100";

export async function POST(request: NextRequest): Promise<Response> {
  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND_BASE_URL}/chat`, {
      method: "POST",
      headers: {
        "content-type": request.headers.get("content-type") ?? "application/json",
      },
      body: request.body,
      signal: request.signal,
      duplex: "half",
    } as RequestInit & { duplex: "half" });
  } catch {
    return Response.json(
      { code: "provider_unavailable", message: "The backend is unavailable." },
      { status: 502 },
    );
  }

  const headers = new Headers();
  const contentType = upstream.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  headers.set("cache-control", "no-cache, no-transform");
  headers.set("x-accel-buffering", "no");

  return new Response(upstream.body, { status: upstream.status, headers });
}
