export const dynamic = "force-dynamic";

type RouteContext = {
  params: Promise<{ path?: string[] }>;
};

const HOP_BY_HOP_HEADERS = [
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];

const PLACEHOLDER_TOKENS = new Set([
  "change-me",
  "change-me-long-random-token",
  "changeme",
  "please-change-me",
  "replace-me",
  "secret",
  "password",
]);

function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function backendOrigin(): string {
  return stripTrailingSlash(process.env.NEXT_BACKEND_ORIGIN?.trim() || "http://api:8000");
}

function apiToken(): string {
  const token = process.env.API_AUTH_TOKEN?.trim() || "";
  if (!token || PLACEHOLDER_TOKENS.has(token.toLowerCase())) {
    throw new Error("API_AUTH_TOKEN is not configured for the web API proxy.");
  }
  return token;
}

function proxiedHeaders(request: Request, token: string): Headers {
  const headers = new Headers(request.headers);
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }
  headers.set("authorization", `Bearer ${token}`);
  return headers;
}

function responseHeaders(response: Response): Headers {
  const headers = new Headers(response.headers);
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }
  return headers;
}

async function proxyRequest(request: Request, context: RouteContext): Promise<Response> {
  let token: string;
  try {
    token = apiToken();
  } catch {
    return Response.json({ detail: "API proxy is not configured." }, { status: 500 });
  }

  const params = await context.params;
  const sourceUrl = new URL(request.url);
  const path = (params.path || []).map((segment) => encodeURIComponent(segment)).join("/");
  const targetUrl = new URL(`/${path}${sourceUrl.search}`, backendOrigin());
  const init: RequestInit = {
    method: request.method,
    headers: proxiedHeaders(request, token),
    redirect: "manual",
    cache: "no-store",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    const body = await request.arrayBuffer();
    if (body.byteLength > 0) {
      init.body = body;
    }
  }

  const response = await fetch(targetUrl, init);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders(response),
  });
}

export function GET(request: Request, context: RouteContext): Promise<Response> {
  return proxyRequest(request, context);
}

export function POST(request: Request, context: RouteContext): Promise<Response> {
  return proxyRequest(request, context);
}

export function PUT(request: Request, context: RouteContext): Promise<Response> {
  return proxyRequest(request, context);
}

export function PATCH(request: Request, context: RouteContext): Promise<Response> {
  return proxyRequest(request, context);
}

export function DELETE(request: Request, context: RouteContext): Promise<Response> {
  return proxyRequest(request, context);
}

export function HEAD(request: Request, context: RouteContext): Promise<Response> {
  return proxyRequest(request, context);
}
