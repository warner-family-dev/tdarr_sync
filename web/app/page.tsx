import AutoRefresh from "./AutoRefresh";
import DatabaseRemovalControl from "./DatabaseRemovalControl";
import RestoreOriginals from "./RestoreOriginals";
import TriggerSyncControl from "./TriggerSyncControl";
import { apiFetchJson } from "./apiClient";

export const dynamic = "force-dynamic";

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
  progress: SyncProgress | null;
  tdarr: TdarrStatus | null;
};

type SyncProgress = {
  run_id: string;
  state: string;
  phase: string;
  action: string;
  source: string | null;
  title: string | null;
  path: string | null;
  destination: string | null;
  message: string | null;
  completed_items: number;
  total_items: number | null;
  skipped_items: number;
  failed_items: number;
  percent: number | null;
  eta_seconds: number | null;
  elapsed_seconds: number | null;
  updated_at_iso: string | null;
};

type TdarrWorkerStatus = {
  id: string;
  name: string;
  node: string;
  node_id: string;
  status: string;
  file: string | null;
  title: string | null;
  progress: number | null;
  eta_seconds: number | null;
};

type TdarrNodeStatus = {
  id: string;
  name: string;
  address: string;
  paused: boolean;
  worker_limit: number;
  active_worker_count: number;
  workers: TdarrWorkerStatus[];
};

type TdarrStatus = {
  configured: boolean;
  reachable: boolean;
  server_url: string;
  error: string | null;
  queue_count: number | null;
  error_count: number | null;
  job_error_count: number | null;
  show_job_error_count: boolean;
  active_worker_count: number;
  workers: TdarrWorkerStatus[];
  nodes: TdarrNodeStatus[];
};

const DISPLAY_TIMEZONE = process.env.TZ ?? Intl.DateTimeFormat().resolvedOptions().timeZone;

const timestampFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: DISPLAY_TIMEZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: true,
});

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) {
    return "—";
  }

  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }

  const parts = timestampFormatter.formatToParts(date);
  const map = new Map(parts.map(({ type, value }) => [type, value]));
  const year = map.get("year");
  const month = map.get("month");
  const day = map.get("day");
  const hour = map.get("hour");
  const minute = map.get("minute");
  const dayPeriod = (map.get("dayPeriod") ?? "").replace(".", "").toUpperCase();

  if (!year || !month || !day || !hour || !minute || !dayPeriod) {
    return timestampFormatter.format(date);
  }

  return `${year}-${month}-${day}  ${hour}:${minute}${dayPeriod}`;
}

async function loadDashboardData() {
  try {
    const [summary, files, status] = await Promise.all([
      apiFetchJson<Summary>("/metrics/summary", { cache: "no-store" }),
      apiFetchJson<ProcessedFile[]>("/processed-files?limit=25", { cache: "no-store" }),
      apiFetchJson<SyncStatus>("/sync/status", { cache: "no-store" }),
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

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return "—";
  }
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  if (minutes < 60) {
    return `${minutes}m ${remainder}s`;
  }
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function phaseLabel(phase: string | undefined): string {
  switch (phase) {
    case "copy_sonarr":
      return "Copying Sonarr files";
    case "copy_radarr":
      return "Copying Radarr files";
    case "restore_outputs":
      return "Restoring Tdarr outputs";
    case "sweep_archives":
      return "Sweeping archived originals";
    case "starting":
      return "Starting sync";
    case "complete":
      return "Sync complete";
    case "failed":
      return "Sync failed";
    default:
      return phase || "Sync progress";
  }
}

function fileName(path: string | null | undefined): string {
  if (!path) {
    return "";
  }
  const normalized = path.replace(/\\/g, "/");
  return normalized.split("/").filter(Boolean).pop() ?? path;
}

function isVisibleTdarrWorker(worker: TdarrWorkerStatus): boolean {
  if (worker.file || worker.title) {
    return true;
  }
  if (worker.progress !== null && worker.progress < 100) {
    return true;
  }
  const status = worker.status.trim().toLowerCase();
  if (!status || ["good", "idle", "ready", "online", "connected", "unknown", "available", "inactive"].includes(status)) {
    return false;
  }
  return ["running", "transcod", "health", "process", "ffmpeg", "handbrake", "mkvpropedit", "copy", "scan", "work"].some((token) =>
    status.includes(token),
  );
}

function ProgressBar({ percent }: { percent: number | null | undefined }) {
  if (percent === null || percent === undefined) {
    return (
      <div className="sync-progress-bar">
        <div className="sync-progress-indeterminate" />
      </div>
    );
  }
  return (
    <div className="sync-progress-bar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} role="progressbar">
      <div className="sync-progress-fill" style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
    </div>
  );
}

export default async function DashboardPage() {
  const { summary, files, status, error } = await loadDashboardData();
  const tdarrNodes = status?.tdarr?.nodes ?? [];
  const activeTdarrNodes = tdarrNodes
    .map((node) => ({ ...node, workers: node.workers.filter(isVisibleTdarrWorker) }))
    .filter((node) => node.workers.length > 0);
  const fallbackTdarrWorkers =
    activeTdarrNodes.length === 0 && status?.tdarr?.workers ? status.tdarr.workers.filter(isVisibleTdarrWorker) : [];

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
              <strong>{formatTimestamp(status?.last_started_at_iso)}</strong>
            </span>
            <span>
              Finished:
              <strong>{formatTimestamp(status?.last_finished_at_iso)}</strong>
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
          <TriggerSyncControl disabled={status?.running ?? false} />
          <div className="restore-launch">
            <RestoreOriginals />
          </div>
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
              <strong>{formatTimestamp(summary?.last_processed_at_iso)}</strong>
            </span>
            <span>
              Earliest processed:
              <strong>{formatTimestamp(summary?.earliest_processed_at_iso)}</strong>
            </span>
            <span>
              DB size:
              <strong>{formatBytes(summary?.database_size_bytes ?? null)}</strong>
            </span>
            <span>
              DB updated:
              <strong>{formatTimestamp(summary?.database_last_modified_iso)}</strong>
            </span>
          </div>
          <div className="library-actions">
            <DatabaseRemovalControl disabled={status?.running ?? false} displayTimezone={DISPLAY_TIMEZONE} />
          </div>
        </article>

        <article className="card">
          <h2>Tdarr Queue</h2>
          {!status?.tdarr?.configured && <p className="muted">Tdarr server URL is not configured.</p>}
          {status?.tdarr?.configured && !status.tdarr.reachable && (
            <p className="error-text">{status.tdarr.error || "Unable to reach Tdarr."}</p>
          )}
          {status?.tdarr?.reachable && (
            <div className="metrics">
              <span>
                Active workers:
                <strong>{status.tdarr.active_worker_count}</strong>
              </span>
              <span>
                Queued:
                <strong>{status.tdarr.queue_count ?? "—"}</strong>
              </span>
              <span>
                Current errors:
                <strong>{status.tdarr.error_count ?? "—"}</strong>
              </span>
              {status.tdarr.show_job_error_count && (
                <span>
                  Job errors:
                  <strong>{status.tdarr.job_error_count ?? "—"}</strong>
                </span>
              )}
              {status.tdarr.error && <p className="muted">{status.tdarr.error}</p>}
              {activeTdarrNodes.length === 0 && fallbackTdarrWorkers.length === 0 && <p className="muted">No active transcodes reported.</p>}
              {activeTdarrNodes.map((node) => (
                <div key={node.id} className="tdarr-node">
                  <div className="tdarr-node-header">
                    <strong>{node.name}</strong>
                    <span>
                      {node.workers.length}
                      {node.worker_limit ? ` / ${node.worker_limit}` : ""} active
                    </span>
                  </div>
                  {node.workers.map((worker) => (
                    <div key={`${node.id}-${worker.id}-${worker.file ?? worker.title ?? worker.status}`} className="tdarr-worker">
                      <div className="sync-progress-header">
                        <strong>{worker.title || fileName(worker.file) || worker.status || "Active transcode"}</strong>
                        <span>{worker.progress !== null ? `${worker.progress.toFixed(1)}%` : worker.status || "active"}</span>
                      </div>
                      <ProgressBar percent={worker.progress} />
                      <div className="sync-progress-meta">
                        {worker.status && <span>{worker.status}</span>}
                        <span>ETA: {formatDuration(worker.eta_seconds)}</span>
                      </div>
                      <div className="sync-progress-current">{worker.file && <code>{worker.file}</code>}</div>
                    </div>
                  ))}
                </div>
              ))}
              {fallbackTdarrWorkers.length > 0 && (
                <div className="tdarr-node">
                  <div className="tdarr-node-header">
                    <strong>Tdarr server</strong>
                    <span>{fallbackTdarrWorkers.length} active</span>
                  </div>
                  {fallbackTdarrWorkers.map((worker) => (
                    <div key={`${worker.id}-${worker.file ?? worker.title ?? worker.status}`} className="tdarr-worker">
                      <div className="sync-progress-header">
                        <strong>{worker.title || fileName(worker.file) || worker.status || "Active transcode"}</strong>
                        <span>{worker.progress !== null ? `${worker.progress.toFixed(1)}%` : worker.status || "active"}</span>
                      </div>
                      <ProgressBar percent={worker.progress} />
                      <div className="sync-progress-meta">
                        {worker.node && <span>{worker.node}</span>}
                        {worker.status && <span>{worker.status}</span>}
                        <span>ETA: {formatDuration(worker.eta_seconds)}</span>
                      </div>
                      <div className="sync-progress-current">{worker.file && <code>{worker.file}</code>}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </article>
      </section>

      {status?.running && status.progress && (
        <section className="card sync-progress-card">
          <h2>Sync Progress</h2>
          <div className="sync-progress-panel">
            <div className="sync-progress-header">
              <strong>{phaseLabel(status.progress.phase)}</strong>
              <span>{status.progress.percent !== null ? `${status.progress.percent.toFixed(1)}%` : "Scanning"}</span>
            </div>
            <ProgressBar percent={status.progress.percent} />
            <div className="sync-progress-meta">
              <span>
                {status.progress.completed_items}
                {status.progress.total_items !== null ? ` / ${status.progress.total_items}` : ""} items
              </span>
              <span>Skipped: {status.progress.skipped_items}</span>
              <span>Failed: {status.progress.failed_items}</span>
              <span>ETA: {formatDuration(status.progress.eta_seconds)}</span>
            </div>
            <div className="sync-progress-current">
              <span>{status.progress.action || "working"}</span>
              {status.progress.title && <strong>{status.progress.title}</strong>}
              {status.progress.path && <code>{status.progress.path}</code>}
              {status.progress.message && <span>{status.progress.message}</span>}
            </div>
          </div>
        </section>
      )}

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
                  <td>{formatTimestamp(file.processed_at_iso)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
