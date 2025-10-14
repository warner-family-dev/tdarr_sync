'use client';

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetchJson } from "./apiClient";

type SeriesStatus = "full" | "partial" | "none";

type RestoreSeasonEntry = {
  number: number;
  name: string;
  processed: number;
  total: number;
  status: SeriesStatus;
  last_processed_at_iso: string | null;
};

type RestoreSeriesEntry = {
  index: number;
  series_id: number;
  title: string;
  processed: number;
  total: number;
  status: SeriesStatus;
  last_processed_at_iso: string | null;
  seasons: RestoreSeasonEntry[];
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
  selected_seasons?: number[] | null;
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

type SeriesSelectionState = {
  allSeasons: boolean;
  seasons: Set<number>;
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
  const [selectedSeries, setSelectedSeries] = useState<Map<number, SeriesSelectionState>>(new Map());
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
      setSelectedSeries((prev) => {
        if (prev.size === 0) {
          return prev;
        }
        const validIds = new Set(payload.series.map((item) => item.series_id));
        const next = new Map<number, SeriesSelectionState>();
        prev.forEach((value, key) => {
          if (validIds.has(key)) {
            next.set(key, { allSeasons: value.allSeasons, seasons: new Set(value.seasons) });
          }
        });
        return next;
      });
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
    setSelectedSeries(new Map());
    setPassword("");
  };

  const toggleSeries = useCallback((seriesId: number, enabled: boolean) => {
    setSelectedSeries((prev) => {
      const next = new Map(prev);
      if (enabled) {
        next.set(seriesId, { allSeasons: true, seasons: new Set() });
      } else {
        next.delete(seriesId);
      }
      return next;
    });
  }, []);

  const toggleAllSeasons = useCallback((seriesId: number, enabled: boolean, seasonNumbers: number[]) => {
    setSelectedSeries((prev) => {
      const next = new Map(prev);
      const current = next.get(seriesId);
      if (!current) {
        if (enabled) {
          next.set(seriesId, { allSeasons: true, seasons: new Set() });
        }
        return next;
      }
      if (enabled) {
        next.set(seriesId, { allSeasons: true, seasons: new Set() });
      } else {
        next.set(seriesId, { allSeasons: false, seasons: new Set(seasonNumbers) });
      }
      return next;
    });
  }, []);

  const toggleSeason = useCallback((seriesId: number, seasonNumber: number, enabled: boolean) => {
    setSelectedSeries((prev) => {
      const next = new Map(prev);
      const current = next.get(seriesId);
      if (!current) {
        if (enabled) {
          next.set(seriesId, { allSeasons: false, seasons: new Set([seasonNumber]) });
        }
        return next;
      }
      const newSet = new Set(current.seasons);
      if (enabled) {
        newSet.add(seasonNumber);
      } else {
        newSet.delete(seasonNumber);
      }
      next.set(seriesId, { allSeasons: false, seasons: newSet });
      return next;
    });
  }, []);

  const hasValidSelection = useMemo(() => {
    if (selectedSeries.size === 0) {
      return false;
    }
    for (const entry of selectedSeries.values()) {
      if (!entry.allSeasons && entry.seasons.size === 0) {
        return false;
      }
    }
    return true;
  }, [selectedSeries]);

  const canSubmit = useMemo(() => {
    return hasValidSelection && password.trim().length > 0 && !submitting;
  }, [hasValidSelection, password, submitting]);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      const selectionsPayload = Array.from(selectedSeries.entries()).map(([seriesId, state]) => ({
        series_id: seriesId,
        seasons: state.allSeasons ? null : Array.from(state.seasons).sort((a, b) => a - b),
      }));

      const invalid = selectionsPayload.some((item) => item.seasons !== null && item.seasons.length === 0);
      if (invalid || selectionsPayload.length === 0) {
        setSubmitError("Select at least one season for each chosen series.");
        setSubmitting(false);
        return;
      }

      const payload = await apiFetchJson<RestoreResponse>("/restore/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selections: selectionsPayload, password }),
      });
      setResult(payload);
      setSelectedSeries(new Map());
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
              Select the series to restore and pick specific seasons (or leave <strong>All seasons</strong> enabled) before
              running the restore. Provide the admin password to confirm. No Tdarr total scan will be triggered.
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
                  {series.map((item) => {
                    const selectionState = selectedSeries.get(item.series_id);
                    const seasonNumbers = item.seasons.map((season) => season.number);
                    return (
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
                          <div className="series-controls">
                            <label className="checkbox-inline">
                              <input
                                type="checkbox"
                                checked={Boolean(selectionState)}
                                onChange={(event) => toggleSeries(item.series_id, event.target.checked)}
                              />
                              <span>Select series</span>
                            </label>

                            {selectionState && (
                              <div className="season-list">
                                <label className="checkbox-inline">
                                  <input
                                    type="checkbox"
                                    checked={selectionState.allSeasons}
                                    onChange={(event) => toggleAllSeasons(item.series_id, event.target.checked, seasonNumbers)}
                                  />
                                  <span>All seasons</span>
                                </label>
                                <div className="season-checkboxes">
                                  {item.seasons.length === 0 && <span className="muted">No seasons found.</span>}
                                  {item.seasons.map((season) => (
                                    <label key={season.number} className="checkbox-inline">
                                      <input
                                        type="checkbox"
                                        checked={
                                          selectionState.allSeasons || selectionState.seasons.has(season.number)
                                        }
                                        disabled={selectionState.allSeasons}
                                        onChange={(event) => toggleSeason(item.series_id, season.number, event.target.checked)}
                                      />
                                      <span>
                                        {season.name}
                                        {" "}
                                        ({season.processed}/{season.total})
                                      </span>
                                    </label>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <form onSubmit={handleSubmit} className="restore-form">
              <label className="form-field">
                <span>Admin password</span>
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Enter password"
                  autoFocus
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
                      <div>
                        <strong>Target seasons:</strong>
                        <span>
                          {(() => {
                            const seasons = seriesResult.selected_seasons;
                            if (!seasons || seasons.length === 0) {
                              return " All seasons";
                            }
                            return ` ${seasons
                              .slice()
                              .sort((a, b) => a - b)
                              .map((value) => value.toString().padStart(2, "0"))
                              .join(", ")}`;
                          })()}
                        </span>
                      </div>
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
