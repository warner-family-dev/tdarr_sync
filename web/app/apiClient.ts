function ensureLeadingSlash(path: string): string {
  if (!path.startsWith("/")) {
    return `/${path}`;
  }
  return path;
}

function buildUrl(path: string): string {
  const normalizedPath = ensureLeadingSlash(path);
  return `/tdarr-api${normalizedPath}`;
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
