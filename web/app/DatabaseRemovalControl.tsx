'use client';

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetchJson } from "./apiClient";

type ProcessedDatabaseFile = {
  file_path: string;
  file_name: string;
  processed_at: number | null;
  processed_at_iso: string | null;
};

type ProcessedDatabaseSeason = {
  number: number;
  name: string;
  file_count: number;
  last_processed_at: number | null;
  last_processed_at_iso: string | null;
  files: ProcessedDatabaseFile[];
};

type ProcessedDatabaseGroup = {
  id: string;
  type: "tv" | "movie" | "folder";
  title: string;
  path: string;
  file_count: number;
  last_processed_at: number | null;
  last_processed_at_iso: string | null;
  seasons: ProcessedDatabaseSeason[];
  files: ProcessedDatabaseFile[];
};

type ProcessedDatabaseCatalog = {
  total_files: number;
  tv: ProcessedDatabaseGroup[];
  movies: ProcessedDatabaseGroup[];
  folders: ProcessedDatabaseGroup[];
};

type DeleteResponse = {
  requested_count: number;
  deleted_count: number;
};

type DatabaseRemovalControlProps = {
  disabled?: boolean;
  displayTimezone: string;
};

function buildErrorMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return "Unable to update database records.";
}

function collectGroupPaths(group: ProcessedDatabaseGroup): string[] {
  if (group.seasons.length > 0) {
    return group.seasons.flatMap((season) => season.files.map((file) => file.file_path));
  }
  return group.files.map((file) => file.file_path);
}

function formatTimestamp(iso: string | null | undefined, formatter: Intl.DateTimeFormat): string {
  if (!iso) {
    return "-";
  }

  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }

  return formatter.format(date);
}

function selectionState(paths: string[], selectedPaths: Set<string>): boolean {
  return paths.length > 0 && paths.every((path) => selectedPaths.has(path));
}

export default function DatabaseRemovalControl({ disabled = false, displayTimezone }: DatabaseRemovalControlProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<ProcessedDatabaseCatalog | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());

  const timestampFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat("en-US", {
        timeZone: displayTimezone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: true,
      }),
    [displayTimezone],
  );

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await apiFetchJson<ProcessedDatabaseCatalog>("/processed-files/catalog", { cache: "no-store" });
      setCatalog(payload);
      setSelectedPaths((prev) => {
        if (prev.size === 0) {
          return prev;
        }
        const validPaths = new Set<string>();
        payload.tv.forEach((group) => collectGroupPaths(group).forEach((path) => validPaths.add(path)));
        payload.movies.forEach((group) => collectGroupPaths(group).forEach((path) => validPaths.add(path)));
        payload.folders.forEach((group) => collectGroupPaths(group).forEach((path) => validPaths.add(path)));
        const next = new Set<string>();
        prev.forEach((path) => {
          if (validPaths.has(path)) {
            next.add(path);
          }
        });
        return next;
      });
    } catch (err) {
      setCatalog(null);
      setError(buildErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const openModal = () => {
    setOpen(true);
    setFeedback(null);
    void loadCatalog();
  };

  const closeModal = () => {
    if (submitting) {
      return;
    }
    setOpen(false);
  };

  const togglePaths = (paths: string[], enabled: boolean) => {
    setSelectedPaths((prev) => {
      const next = new Set(prev);
      paths.forEach((path) => {
        if (enabled) {
          next.add(path);
        } else {
          next.delete(path);
        }
      });
      return next;
    });
  };

  const removeSelected = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const paths = Array.from(selectedPaths).sort();
    if (paths.length === 0 || submitting) {
      return;
    }

    const confirmed = window.confirm(`Remove ${paths.length} selected database record${paths.length === 1 ? "" : "s"}?`);
    if (!confirmed) {
      return;
    }

    setSubmitting(true);
    setError(null);
    setFeedback(null);
    try {
      const response = await apiFetchJson<DeleteResponse>("/processed-files/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_paths: paths }),
      });
      setSelectedPaths(new Set());
      setFeedback(`Removed ${response.deleted_count} of ${response.requested_count} selected database records.`);
      await loadCatalog();
      router.refresh();
    } catch (err) {
      setError(buildErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const renderFile = (file: ProcessedDatabaseFile) => (
    <label key={file.file_path} className="checkbox-inline database-file-row">
      <input
        type="checkbox"
        checked={selectedPaths.has(file.file_path)}
        onChange={(event) => togglePaths([file.file_path], event.target.checked)}
      />
      <span>{file.file_name}</span>
      <small>{formatTimestamp(file.processed_at_iso, timestampFormatter)}</small>
    </label>
  );

  const renderTvGroup = (group: ProcessedDatabaseGroup) => {
    const groupPaths = collectGroupPaths(group);
    return (
      <div key={group.id} className="database-group">
        <label className="checkbox-inline database-group-title">
          <input
            type="checkbox"
            checked={selectionState(groupPaths, selectedPaths)}
            onChange={(event) => togglePaths(groupPaths, event.target.checked)}
          />
          <strong>{group.title}</strong>
          <span>{group.file_count} records</span>
        </label>
        <div className="database-sublist">
          {group.seasons.map((season) => {
            const seasonPaths = season.files.map((file) => file.file_path);
            return (
              <div key={`${group.id}-${season.number}`} className="database-season">
                <label className="checkbox-inline database-season-title">
                  <input
                    type="checkbox"
                    checked={selectionState(seasonPaths, selectedPaths)}
                    onChange={(event) => togglePaths(seasonPaths, event.target.checked)}
                  />
                  <span>{season.name}</span>
                  <small>{season.file_count} records</small>
                </label>
                <div className="database-file-list">{season.files.map(renderFile)}</div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  const renderFlatGroup = (group: ProcessedDatabaseGroup) => {
    const groupPaths = collectGroupPaths(group);
    return (
      <div key={group.id} className="database-group">
        <label className="checkbox-inline database-group-title">
          <input
            type="checkbox"
            checked={selectionState(groupPaths, selectedPaths)}
            onChange={(event) => togglePaths(groupPaths, event.target.checked)}
          />
          <strong>{group.title}</strong>
          <span>{group.file_count} records</span>
        </label>
        <div className="database-file-list">{group.files.map(renderFile)}</div>
      </div>
    );
  };

  return (
    <div className="database-removal-control">
      <button type="button" className="button ghost" onClick={openModal} disabled={disabled}>
        Remove from Database
      </button>
      {feedback && <p className="muted database-feedback">{feedback}</p>}

      {open && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal database-modal">
            <div className="modal-header">
              <h3>Remove From Database</h3>
              <button type="button" className="icon-button" onClick={closeModal} aria-label="Close database removal modal">
                ×
              </button>
            </div>

            <p className="modal-intro">Select processed database records to remove.</p>

            <div className="modal-section">
              <div className="modal-section-header">
                <h4>Database Records</h4>
                <button type="button" className="icon-button small" onClick={loadCatalog} disabled={loading || submitting}>
                  ↻
                </button>
              </div>
              {loading && <p className="muted">Loading database records...</p>}
              {error && <p className="error-text">{error}</p>}
              {!loading && !error && catalog && catalog.total_files === 0 && <p className="muted">No processed records found.</p>}
              {!loading && !error && catalog && catalog.total_files > 0 && (
                <div className="database-list">
                  {catalog.tv.length > 0 && (
                    <section>
                      <h5>TV Shows</h5>
                      {catalog.tv.map(renderTvGroup)}
                    </section>
                  )}
                  {catalog.movies.length > 0 && (
                    <section>
                      <h5>Movies</h5>
                      {catalog.movies.map(renderFlatGroup)}
                    </section>
                  )}
                  {catalog.folders.length > 0 && (
                    <section>
                      <h5>Other Folders</h5>
                      {catalog.folders.map(renderFlatGroup)}
                    </section>
                  )}
                </div>
              )}
            </div>

            <form onSubmit={removeSelected} className="restore-form">
              {error && <p className="error-text">{error}</p>}
              <div className="form-actions">
                <button type="submit" className="button" disabled={selectedPaths.size === 0 || submitting}>
                  {submitting ? "Removing..." : `Remove Selected (${selectedPaths.size})`}
                </button>
                <button type="button" className="button ghost" onClick={closeModal} disabled={submitting}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
