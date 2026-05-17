function ensureLeadingSlash(path: string): string {
  if (!path.startsWith("/")) {
    return `/${path}`;
  }
  return path;
}

function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function buildUrl(path: string): string {
  const normalizedPath = ensureLeadingSlash(path);
  if (typeof window === "undefined") {
    const backendOrigin = stripTrailingSlash(process.env.NEXT_BACKEND_ORIGIN?.trim() || "http://api:8000");
    return `${backendOrigin}${normalizedPath}`;
  }
  return `/tdarr-api${normalizedPath}`;
}

export function apiUrl(path: string): string {
  return buildUrl(path);
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const requestInit = { ...(init || {}) };
  if (typeof window === "undefined") {
    const token = process.env.API_AUTH_TOKEN?.trim();
    if (!token) {
      throw new Error("API_AUTH_TOKEN is not configured for server-side API requests.");
    }
    const headers = new Headers(requestInit.headers);
    headers.set("authorization", `Bearer ${token}`);
    requestInit.headers = headers;
  }
  return fetch(buildUrl(path), requestInit);
}

export async function apiFetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const data = await response.json();
      if (data?.detail) {
        message = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      }
    } catch {
      // ignore JSON parse errors and fall back to status message
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
