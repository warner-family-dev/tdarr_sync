import { createHash, timingSafeEqual } from "node:crypto";
import { requestBypassesWebAuth, trustedProxyClientIp } from "./networkAuth";

const PLACEHOLDER_SECRETS = new Set([
  "change-me",
  "change-me-long-random-password",
  "change-me-long-random-token",
  "changeme",
  "password",
  "please-change-me",
  "replace-me",
  "secret",
]);

const FAILURE_WINDOW_MS = 5 * 60 * 1000;
const BLOCK_DURATION_MS = 15 * 60 * 1000;
const MAX_FAILURES = 5;

type FailureRecord = {
  failures: number;
  windowStartedAt: number;
  blockedUntil: number;
};

export type WebAuthResult = "authenticated" | "misconfigured" | "unauthorized";

const failuresByClient = new Map<string, FailureRecord>();

function safeEqual(left: string, right: string): boolean {
  const leftDigest = createHash("sha256").update(left).digest();
  const rightDigest = createHash("sha256").update(right).digest();
  return timingSafeEqual(leftDigest, rightDigest);
}

function configuredCredentials(): { username: string; password: string } | null {
  const username = process.env.WEB_AUTH_USERNAME?.trim() || "admin";
  const password = process.env.WEB_AUTH_PASSWORD?.trim() || "";
  if (!password || PLACEHOLDER_SECRETS.has(password.toLowerCase())) return null;
  return { username, password };
}

function parsedBasicCredentials(request: Request): { username: string; password: string } | null {
  const authorization = request.headers.get("authorization") || "";
  const [scheme, encoded, ...extra] = authorization.trim().split(/\s+/);
  if (scheme?.toLowerCase() !== "basic" || !encoded || extra.length > 0) return null;

  try {
    const decoded = Buffer.from(encoded, "base64").toString("utf8");
    const separator = decoded.indexOf(":");
    if (separator < 0) return null;
    return {
      username: decoded.slice(0, separator),
      password: decoded.slice(separator + 1),
    };
  } catch {
    return null;
  }
}

export function authenticateWebRequest(request: Request): WebAuthResult {
  if (requestBypassesWebAuth(request)) return "authenticated";
  const configured = configuredCredentials();
  if (!configured) return "misconfigured";

  const supplied = parsedBasicCredentials(request);
  if (!supplied) return "unauthorized";
  return safeEqual(supplied.username, configured.username) &&
    safeEqual(supplied.password, configured.password)
    ? "authenticated"
    : "unauthorized";
}

export function webAuthFailureKey(request: Request): string {
  return trustedProxyClientIp(request) || "direct-client";
}

export function webAuthRetryAfter(clientKey: string, now = Date.now()): number | null {
  const record = failuresByClient.get(clientKey);
  if (!record) return null;
  if (record.blockedUntil <= now) {
    if (now - record.windowStartedAt >= FAILURE_WINDOW_MS) failuresByClient.delete(clientKey);
    return null;
  }
  return Math.max(1, Math.ceil((record.blockedUntil - now) / 1000));
}

export function recordWebAuthFailure(clientKey: string, now = Date.now()): number | null {
  const current = failuresByClient.get(clientKey);
  const record =
    !current || now - current.windowStartedAt >= FAILURE_WINDOW_MS
      ? { failures: 0, windowStartedAt: now, blockedUntil: 0 }
      : current;

  record.failures += 1;
  if (record.failures >= MAX_FAILURES) record.blockedUntil = now + BLOCK_DURATION_MS;
  failuresByClient.set(clientKey, record);

  if (failuresByClient.size > 1_000) {
    for (const [key, value] of failuresByClient) {
      if (value.blockedUntil <= now && now - value.windowStartedAt >= FAILURE_WINDOW_MS) {
        failuresByClient.delete(key);
      }
    }
  }
  return webAuthRetryAfter(clientKey, now);
}

export function clearWebAuthFailures(clientKey: string): void {
  failuresByClient.delete(clientKey);
}

export function webAuthResponse(result: Exclude<WebAuthResult, "authenticated">): Response {
  if (result === "misconfigured") {
    return Response.json(
      { detail: "Dashboard authentication is not configured." },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
  return Response.json(
    { detail: "Unauthorized" },
    {
      status: 401,
      headers: {
        "Cache-Control": "no-store",
        "WWW-Authenticate": 'Basic realm="Tdarr Sync", charset="UTF-8"',
      },
    },
  );
}

export function isTrustedMutationOrigin(request: Request): boolean {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method.toUpperCase())) return true;

  const allowed = new Set([new URL(request.url).origin]);
  for (const rawOrigin of (process.env.WEB_ALLOWED_ORIGINS || "").split(",")) {
    const value = rawOrigin.trim();
    if (!value) continue;
    try {
      allowed.add(new URL(value).origin);
    } catch {
      // Ignore malformed operator configuration rather than trusting it.
    }
  }

  const origin = request.headers.get("origin");
  if (origin) {
    try {
      return allowed.has(new URL(origin).origin);
    } catch {
      return false;
    }
  }
  return request.headers.get("sec-fetch-site")?.toLowerCase() !== "cross-site";
}
