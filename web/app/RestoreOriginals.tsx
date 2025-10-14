'use client';

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetchJson } from "./apiClient";

type SeriesStatus = "full" | "partial" | "none";

type RestoreSeriesEntry = {
  index: number;
  series_id: number;
  title: string;
  processed: number;
  total: number;
  status: SeriesStatus;
  last_processed_at_iso: string | null;
};

type RestoreSummary = {
  series_requested: number;
  series_processed: number;
  files_restored: number;
  files_skipped_missing_db: number;
  files_skipped_missing_archive: number;
};

type RestoreSeriesResult = {
  series_id: number;
  title: string;
  restored: string[];
  archived_transcodes: string[];
  skipped_missing_db: string[];
  skipped_missing_archive: string[];
  skipped_outside_library: string[];
  errors: string[];
};

type RestoreResponse = {
  summary: RestoreSummary;
  results: RestoreSeriesResult[];
  messages: string[];
};

function statusLabel(status: SeriesStatus): string {
  switch (status) {
    case "full":
      return "✓ Fully processed";
    case "partial":
      return "◐ Partially processed";
    default:
      return "○ Not processed";
  }
}

function statusBadgeClass(status: SeriesStatus): string {
  switch (status) {
    case "full":
      return "status-badge ok";
    case "partial":
      return "status-badge warn";
    default:
      return "status-badge";
  }
}

function buildErrorMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

export default function RestoreOriginalsControl() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [series, setSeries] = useState<RestoreSeriesEntry[]>([]);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [seriesError, setSeriesError] = useState<string | null>(null);

  const [selection, setSelection] = useState("");
  const [password, setPassword] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<RestoreResponse | null>(null);

  const loadSeries = useCallback(async () => {
    setSeriesLoading(true);
    setSeriesError(null);
    try {
      const payload = await apiFetchJson<{ series: RestoreSeriesEntry[] }>("/restore/series", {
        cache: "no-store",
      });
      setSeries(payload.series);
    } catch (error) {
      setSeriesError(buildErrorMessage(error));
      setSeries([]);
    } finally {
      setSeriesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    loadSeries();
  }, [open, loadSeries]);

  const handleOpen = () => {
    setOpen(true);
    setSubmitError(null);
    setResult(null);
  };

  const handleClose = () => {
    setOpen(false);
    setSubmitError(null);
    setSubmitting(false);
    setResult(null);
    setSelection("");
    setPassword("");
  };

  const canSubmit = useMemo(() => {
    return selection.trim().length > 0 && password.trim().length > 0 && !submitting;
  }, [password, selection, submitting]);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      const payload = await apiFetchJson<RestoreResponse>("/restore/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selection: selection.trim(), password }),
      });
      setResult(payload);
      setSelection("");
      setPassword("");
      await loadSeries();
      router.refresh();
    } catch (error) {
      setSubmitError(buildErrorMessage(error));
      setResult(null);
    } finally {
      setSubmitting(false);
    }
  };

  const summaryItems = useMemo(() => {
    if (!result) return [];
    const { summary } = result;
    return [
      { label: "Series requested", value: summary.series_requested },
      { label: "Series processed", value: summary.series_processed },
      { label: "Files restored", value: summary.files_restored },
      { label: "Missing in DB", value: summary.files_skipped_missing_db },
      { label: "Missing original", value: summary.files_skipped_missing_archive },
    ];
  }, [result]);

  return (
    <div className="restore-control">
      <button type="button" className="button secondary" onClick={handleOpen}>
        Restore Originals
      </button>

      {open && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal">
            <div className="modal-header">
              <h3>Restore Originals</h3>
              <button type="button" className="icon-button" onClick={handleClose} aria-label="Close restore modal">
                ×
              </button>
            </div>

            <p className="modal-intro">
              Select the series to restore back to their original files. Provide selection indexes (e.g. <code>1,3,6</code>{" "}
              or <code>1-4,6</code> or <code>all</code>) and the admin password. No Tdarr total scan will be triggered.
            </p>

            <div className="modal-section">
              <div className="modal-section-header">
                <h4>Series</h4>
                <button type="button" className="icon-button small" onClick={loadSeries} disabled={seriesLoading}>
                  ↻
                </button>
              </div>
              {seriesLoading && <p className="muted">Loading series…</p>}
              {seriesError && <p className="error-text">{seriesError}</p>}
              {!seriesLoading && !seriesError && series.length === 0 && <p className="muted">No series available.</p>}
              {!seriesLoading && !seriesError && series.length > 0 && (
                <div className="series-list">
                  {series.map((item) => (
                    <div key={item.series_id} className="series-row">
                      <span className="series-index">{item.index}.</span>
                      <div className="series-info">
                        <div className="series-title">
                          <span className={statusBadgeClass(item.status)}>{statusLabel(item.status)}</span>
                          <strong>{item.title}</strong>
                        </div>
                        <div className="series-meta">
                          <span>
                            {item.processed} / {item.total} processed
                          </span>
                          <span>{item.last_processed_at_iso ? `Last: ${item.last_processed_at_iso}` : "Never processed"}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <form onSubmit={handleSubmit} className="restore-form">
              <label className="form-field">
                <span>Series selection</span>
                <input
                  type="text"
                  value={selection}
                  onChange={(event) => setSelection(event.target.value)}
                  placeholder="e.g. 1-3,5 or all"
                  autoFocus
                />
              </label>
              <label className="form-field">
                <span>Admin password</span>
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Enter password"
                />
              </label>
              {submitError && <p className="error-text">{submitError}</p>}
              <div className="form-actions">
                <button type="submit" className="button" disabled={!canSubmit}>
                  {submitting ? "Restoring…" : "Run Restore"}
                </button>
                <button type="button" className="button ghost" onClick={handleClose} disabled={submitting}>
                  Cancel
                </button>
              </div>
            </form>

            {result && (
              <div className="modal-section">
                <h4>Result</h4>
                <ul className="summary-list">
                  {summaryItems.map((item) => (
                    <li key={item.label}>
                      <strong>{item.value}</strong> {item.label}
                    </li>
                  ))}
                </ul>
                {result.messages.length > 0 && (
                  <ul className="message-list">
                    {result.messages.map((message, index) => (
                      <li key={index}>{message}</li>
                    ))}
                  </ul>
                )}
                {result.results.map((seriesResult) => (
                  <details key={seriesResult.series_id} className="series-result">
                    <summary>{seriesResult.title}</summary>
                    <div className="series-result-body">
                      {seriesResult.restored.length > 0 && (
                        <div>
                          <strong>Restored:</strong>
                          <ul>
                            {seriesResult.restored.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {seriesResult.skipped_missing_db.length > 0 && (
                        <div>
                          <strong>Skipped (not in DB):</strong>
                          <ul>
                            {seriesResult.skipped_missing_db.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {seriesResult.skipped_missing_archive.length > 0 && (
                        <div>
                          <strong>Skipped (missing original):</strong>
                          <ul>
                            {seriesResult.skipped_missing_archive.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {seriesResult.skipped_outside_library.length > 0 && (
                        <div>
                          <strong>Skipped (outside library root):</strong>
                          <ul>
                            {seriesResult.skipped_outside_library.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {seriesResult.errors.length > 0 && (
                        <div>
                          <strong>Errors:</strong>
                          <ul className="error-list">
                            {seriesResult.errors.map((item, index) => (
                              <li key={`${seriesResult.series_id}-error-${index}`}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  </details>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
