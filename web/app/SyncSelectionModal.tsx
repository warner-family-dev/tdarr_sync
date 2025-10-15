'use client';

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetchJson } from "./apiClient";

type SeriesStatus = "full" | "partial" | "none";

type SyncSeasonEntry = {
  number: number;
  name: string;
  processed: number;
  total: number;
  status: SeriesStatus;
  last_processed_at_iso: string | null;
};

type SyncSeriesEntry = {
  index: number;
  series_id: number;
  title: string;
  processed: number;
  total: number;
  status: SeriesStatus;
  last_processed_at_iso: string | null;
  seasons: SyncSeasonEntry[];
};

type SeriesSelectionState = {
  allSeasons: boolean;
  seasons: Set<number>;
};

type SyncSelectionModalProps = {
  dryRun: boolean;
  onClose: () => void;
  onCompleted: (message: string) => void;
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

export default function SyncSelectionModal({ dryRun, onClose, onCompleted }: SyncSelectionModalProps) {
  const [series, setSeries] = useState<SyncSeriesEntry[]>([]);
  const [seriesLoading, setSeriesLoading] = useState(true);
  const [seriesError, setSeriesError] = useState<string | null>(null);
  const [selectedSeries, setSelectedSeries] = useState<Map<number, SeriesSelectionState>>(new Map());
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const loadSeries = useCallback(async () => {
    setSeriesLoading(true);
    setSeriesError(null);
    try {
      const payload = await apiFetchJson<{ series: SyncSeriesEntry[] }>("/restore/series", { cache: "no-store" });
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
    loadSeries();
  }, [loadSeries]);

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
    for (const entry of Array.from(selectedSeries.values())) {
      if (!entry.allSeasons && entry.seasons.size === 0) {
        return false;
      }
    }
    return true;
  }, [selectedSeries]);

  const canSubmit = hasValidSelection && !submitting;

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

      await apiFetchJson("/sync/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dry_run: dryRun, selections: selectionsPayload }),
      });

      setSelectedSeries(new Map());
      onCompleted(dryRun ? "Dry run sync triggered." : "Sync triggered.");
      onClose();
    } catch (error) {
      setSubmitError(buildErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal">
        <div className="modal-header">
          <h3>Select Series To Sync</h3>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close sync selection modal">
            ×
          </button>
        </div>

        <p className="modal-intro">
          Choose which series (and optional seasons) to include in this
          {" "}
          {dryRun ? "dry run." : "sync run."}
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
                          {item.processed}
                          {" "}
                          /
                          {" "}
                          {item.total}
                          {" "}
                          processed
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
                                    checked={selectionState.allSeasons || selectionState.seasons.has(season.number)}
                                    disabled={selectionState.allSeasons}
                                    onChange={(event) => toggleSeason(item.series_id, season.number, event.target.checked)}
                                  />
                                  <span>
                                    {season.name}
                                    {" "}
                                    (
                                    {season.processed}
                                    /
                                    {season.total}
                                    )
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
          {submitError && <p className="error-text">{submitError}</p>}
          <div className="form-actions">
            <button type="submit" className="button" disabled={!canSubmit}>
              {submitting ? "Triggering…" : dryRun ? "Run Dry Sync" : "Trigger Sync"}
            </button>
            <button type="button" className="button ghost" onClick={onClose} disabled={submitting}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
