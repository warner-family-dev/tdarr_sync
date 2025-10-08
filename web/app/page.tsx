import AutoRefresh from "./AutoRefresh";
import { triggerSyncAction } from "./actions";

type ProcessedFile = {
  file_path: string;
  processed_at: number | null;
  processed_at_iso: string | null;
};

type Summary = {
  total_processed: number;
  last_processed_at: number | null;
  last_processed_at_iso: string | null;
  earliest_processed_at: number | null;
  earliest_processed_at_iso: string | null;
  database_size_bytes: number | null;
  database_last_modified_iso: string | null;
};

type SyncStatus = {
  running: boolean;
  last_started_at: number | null;
  last_started_at_iso: string | null;
  last_finished_at: number | null;
  last_finished_at_iso: string | null;
  last_exit_code: number | null;
  last_error: string | null;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

async function loadDashboardData() {
  try {
    const [summary, files, status] = await Promise.all([
      fetchJson<Summary>("/metrics/summary"),
      fetchJson<ProcessedFile[]>("/processed-files?limit=25"),
      fetchJson<SyncStatus>("/sync/status"),
    ]);
    return { summary, files, status, error: null as string | null };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Unable to reach Tdarr Sync API";
    return { summary: null, files: [] as ProcessedFile[], status: null, error: message };
  }
}

function formatBytes(bytes: number | null): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(1)} ${units[index]}`;
}

export default async function DashboardPage() {
  const { summary, files, status, error } = await loadDashboardData();
  return (
    <div>
      <AutoRefresh initialStatus={status} intervalMs={5000} />
      {error && <div className="error-banner">⚠️ {error}</div>}

      <section className="grid">
        <article className="card">
          <h2>Sync Status</h2>
          <div className="metrics">
            <span>
              Status:
              <span className="status">
                <span className={`status-dot ${status?.running ? "ok" : status?.last_error ? "error" : "warn"}`} />
                {status?.running ? "Running" : status?.last_error ? "Attention" : "Idle"}
              </span>
            </span>
            <span>
              Last Run:
              <strong>{status?.last_started_at_iso ?? "—"}</strong>
            </span>
            <span>
              Finished:
              <strong>{status?.last_finished_at_iso ?? "—"}</strong>
            </span>
            <span>
              Exit Code:
              <strong>{status?.last_exit_code ?? "—"}</strong>
            </span>
            {status?.last_error && (
              <span>
                Error:
                <strong>{status.last_error}</strong>
              </span>
            )}
          </div>
          <form action={triggerSyncAction} className="trigger-form">
            <button className="button" type="submit" disabled={status?.running}>
              Trigger Sync
            </button>
            <label className="checkbox">
              <input name="dry-run" type="checkbox" defaultChecked={false} />
              Dry run
            </label>
          </form>
        </article>

        <article className="card">
          <h2>Library Metrics</h2>
          <div className="metrics">
            <span>
              Files processed:
              <strong>{summary?.total_processed ?? 0}</strong>
            </span>
            <span>
              Last processed:
              <strong>{summary?.last_processed_at_iso ?? "—"}</strong>
            </span>
            <span>
              Earliest processed:
              <strong>{summary?.earliest_processed_at_iso ?? "—"}</strong>
            </span>
            <span>
              DB size:
              <strong>{formatBytes(summary?.database_size_bytes ?? null)}</strong>
            </span>
            <span>
              DB updated:
              <strong>{summary?.database_last_modified_iso ?? "—"}</strong>
            </span>
          </div>
        </article>
      </section>

      <section className="card">
        <h2>Recent Files</h2>
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Processed At</th>
              </tr>
            </thead>
            <tbody>
              {files.length === 0 && (
                <tr>
                  <td colSpan={2}>No file history yet.</td>
                </tr>
              )}
              {files.map((file) => (
                <tr key={`${file.file_path}-${file.processed_at}`}>
                  <td>{file.file_path}</td>
                  <td>{file.processed_at_iso ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
