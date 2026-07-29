import { type NextRequest, NextResponse } from "next/server";
import {
  authenticateWebRequest,
  clearWebAuthFailures,
  recordWebAuthFailure,
  webAuthFailureKey,
  webAuthResponse,
  webAuthRetryAfter,
} from "./auth";

export function proxy(request: NextRequest): Response {
  const result = authenticateWebRequest(request);
  if (result === "misconfigured") return webAuthResponse(result);

  const clientKey = webAuthFailureKey(request);
  const retryAfter = webAuthRetryAfter(clientKey);
  if (retryAfter !== null) {
    return Response.json(
      { detail: "Too many authentication failures. Try again later." },
      {
        status: 429,
        headers: {
          "Cache-Control": "no-store",
          "Retry-After": String(retryAfter),
        },
      },
    );
  }

  if (result === "unauthorized") {
    const blockedFor = recordWebAuthFailure(clientKey);
    if (blockedFor !== null) {
      return Response.json(
        { detail: "Too many authentication failures. Try again later." },
        {
          status: 429,
          headers: {
            "Cache-Control": "no-store",
            "Retry-After": String(blockedFor),
          },
        },
      );
    }
    return webAuthResponse(result);
  }

  clearWebAuthFailures(clientKey);
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
