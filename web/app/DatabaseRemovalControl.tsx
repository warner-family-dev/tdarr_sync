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

type Category = "tv" | "movies" | "folders";

type ViewState =
  | { level: "root" }
  | { level: "category"; category: Category }
  | { level: "group"; category: Category; groupId: string }
  | { level: "season"; category: "tv"; groupId: string; seasonNumber: number };

const ROOT_VIEW: ViewState = { level: "root" };

function buildErrorMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return "Unable to update database records.";
}

function categoryLabel(category: Category): string {
  switch (category) {
    case "tv":
      return "TV Shows";
    case "movies":
      return "Movies";
    default:
      return "Other Folders";
  }
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

function isFullySelected(paths: string[], selectedPaths: Set<string>): boolean {
  return paths.length > 0 && paths.every((path) => selectedPaths.has(path));
}

function pluralize(count: number, singular: string): string {
  return `${count} ${singular}${count === 1 ? "" : "s"}`;
}

export default function DatabaseRemovalControl({ disabled = false, displayTimezone }: DatabaseRemovalControlProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<ProcessedDatabaseCatalog | null>(null);
  const [view, setView] = useState<ViewState>(ROOT_VIEW);
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

  const groupsForCategory = useCallback(
    (category: Category): ProcessedDatabaseGroup[] => {
      if (!catalog) {
        return [];
      }
      return catalog[category];
    },
    [catalog],
  );

  const currentGroup = useMemo(() => {
    if (view.level !== "group" && view.level !== "season") {
      return null;
    }
    return groupsForCategory(view.category).find((group) => group.id === view.groupId) ?? null;
  }, [groupsForCategory, view]);

  const currentSeason = useMemo(() => {
    if (view.level !== "season" || !currentGroup) {
      return null;
    }
    return currentGroup.seasons.find((season) => season.number === view.seasonNumber) ?? null;
  }, [currentGroup, view]);

  const selectedCount = selectedPaths.size;

  const openModal = () => {
    setOpen(true);
    setView(ROOT_VIEW);
    setFeedback(null);
    void loadCatalog();
  };

  const closeModal = () => {
    if (submitting) {
      return;
    }
    setOpen(false);
  };

  const goBack = () => {
    if (view.level === "season") {
      setView({ level: "group", category: view.category, groupId: view.groupId });
      return;
    }
    if (view.level === "group") {
      setView({ level: "category", category: view.category });
      return;
    }
    if (view.level === "category") {
      setView(ROOT_VIEW);
    }
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

    const confirmed = window.confirm(`Remove ${pluralize(paths.length, "selected database record")}?`);
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
      setView(ROOT_VIEW);
      router.refresh();
    } catch (err) {
      setError(buildErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const renderHeader = () => {
    let title = "Database Records";
    if (view.level === "category") {
      title = categoryLabel(view.category);
    } else if (view.level === "group" && currentGroup) {
      title = currentGroup.title;
    } else if (view.level === "season" && currentSeason) {
      title = currentSeason.name;
    }

    return (
      <div className="modal-section-header database-browser-header">
        <div>
          {view.level !== "root" && (
            <button type="button" className="button ghost database-back" onClick={goBack} disabled={submitting}>
              Back
            </button>
          )}
          <h4>{title}</h4>
        </div>
        <button type="button" className="icon-button small" onClick={loadCatalog} disabled={loading || submitting}>
          ↻
        </button>
      </div>
    );
  };

  const renderRoot = () => {
    if (!catalog) {
      return null;
    }

    const categories = [
      { category: "tv" as const, count: catalog.tv.length },
      { category: "movies" as const, count: catalog.movies.length },
      { category: "folders" as const, count: catalog.folders.length },
    ].filter((item) => item.count > 0);

    return (
      <div className="database-drill-list">
        {categories.map((item) => (
          <button
            key={item.category}
            type="button"
            className="database-drill-row"
            onClick={() => setView({ level: "category", category: item.category })}
          >
            <span>{categoryLabel(item.category)}</span>
            <small>{pluralize(item.count, item.category === "movies" ? "movie" : "group")}</small>
          </button>
        ))}
      </div>
    );
  };

  const renderCategory = () => {
    if (view.level !== "category") {
      return null;
    }

    const groups = groupsForCategory(view.category);
    return (
      <div className="database-drill-list">
        {groups.map((group) => {
          const paths = collectGroupPaths(group);
          return (
            <div key={group.id} className="database-select-row">
              <label className="checkbox-inline">
                <input
                  type="checkbox"
                  checked={isFullySelected(paths, selectedPaths)}
                  onChange={(event) => togglePaths(paths, event.target.checked)}
                />
                <span>{group.title}</span>
                <small>{pluralize(group.file_count, "record")}</small>
              </label>
              <button
                type="button"
                className="button ghost database-open"
                onClick={() => setView({ level: "group", category: view.category, groupId: group.id })}
              >
                Open
              </button>
            </div>
          );
        })}
      </div>
    );
  };

  const renderGroup = () => {
    if (view.level !== "group" || !currentGroup) {
      return null;
    }

    if (view.category === "tv") {
      return (
        <div className="database-drill-list">
          {currentGroup.seasons.map((season) => {
            const paths = season.files.map((file) => file.file_path);
            return (
              <div key={`${currentGroup.id}-${season.number}`} className="database-select-row">
                <label className="checkbox-inline">
                  <input
                    type="checkbox"
                    checked={isFullySelected(paths, selectedPaths)}
                    onChange={(event) => togglePaths(paths, event.target.checked)}
                  />
                  <span>{season.name}</span>
                  <small>{pluralize(season.file_count, "record")}</small>
                </label>
                <button
                  type="button"
                  className="button ghost database-open"
                  onClick={() => setView({ level: "season", category: "tv", groupId: currentGroup.id, seasonNumber: season.number })}
                >
                  Open
                </button>
              </div>
            );
          })}
        </div>
      );
    }

    return <div className="database-drill-list">{currentGroup.files.map(renderFileRow)}</div>;
  };

  const renderSeason = () => {
    if (view.level !== "season" || !currentSeason) {
      return null;
    }

    return <div className="database-drill-list">{currentSeason.files.map(renderFileRow)}</div>;
  };

  const renderFileRow = (file: ProcessedDatabaseFile) => (
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

  const renderBrowser = () => {
    if (loading) {
      return <p className="muted">Loading database records...</p>;
    }
    if (error) {
      return <p className="error-text">{error}</p>;
    }
    if (!catalog || catalog.total_files === 0) {
      return <p className="muted">No processed records found.</p>;
    }
    if (view.level === "root") {
      return renderRoot();
    }
    if (view.level === "category") {
      return renderCategory();
    }
    if (view.level === "group") {
      return renderGroup();
    }
    return renderSeason();
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

            <p className="modal-intro">Drill into the database records and select the items to remove.</p>

            <div className="modal-section database-browser">
              {renderHeader()}
              {renderBrowser()}
            </div>

            <form onSubmit={removeSelected} className="restore-form">
              {error && <p className="error-text">{error}</p>}
              <div className="form-actions">
                <button type="submit" className="button" disabled={selectedCount === 0 || submitting}>
                  {submitting ? "Removing..." : `Remove Selected (${selectedCount})`}
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
