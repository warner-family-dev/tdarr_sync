function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function ensureLeadingSlash(path: string): string {
  if (!path.startsWith("/")) {
    return `/${path}`;
  }
  return path;
}

function resolveApiBase(): string {
  if (typeof window !== "undefined") {
    const publicOrigin = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
    if (publicOrigin) {
      return stripTrailingSlash(publicOrigin);
    }
  }

  const backendOrigin = process.env.NEXT_BACKEND_ORIGIN?.trim();
  if (backendOrigin && backendOrigin.length > 0) {
    return stripTrailingSlash(backendOrigin);
  }

  return "/tdarr-api";
}

function buildUrl(path: string): string {
  const apiBase = resolveApiBase();
  const normalizedPath = ensureLeadingSlash(path);
  if (apiBase.startsWith("http")) {
    return `${apiBase}${normalizedPath}`;
  }
  return `${apiBase}${normalizedPath}`;
}

export function apiUrl(path: string): string {
  return buildUrl(path);
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(buildUrl(path), init);
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
