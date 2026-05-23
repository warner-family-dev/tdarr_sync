'use client';

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetchJson } from "./apiClient";

type ProcessedFile = {
  file_path: string;
  processed_at: number | null;
  processed_at_iso: string | null;
};

type DeleteResponse = {
  deleted: boolean;
  deleted_count: number;
  file_path: string;
};

type ProcessedFilesTableProps = {
  files: ProcessedFile[];
  displayTimezone: string;
};


function formatTimestamp(iso: string | null | undefined, formatter: Intl.DateTimeFormat): string {
  if (!iso) {
    return "—";
  }

  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }

  const parts = formatter.formatToParts(date);
  const map = new Map(parts.map(({ type, value }) => [type, value]));
  const year = map.get("year");
  const month = map.get("month");
  const day = map.get("day");
  const hour = map.get("hour");
  const minute = map.get("minute");
  const dayPeriod = (map.get("dayPeriod") ?? "").replace(".", "").toUpperCase();

  if (!year || !month || !day || !hour || !minute || !dayPeriod) {
    return formatter.format(date);
  }

  return `${year}-${month}-${day}  ${hour}:${minute}${dayPeriod}`;
}

function buildErrorMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return "Failed to remove processed marker.";
}

export default function ProcessedFilesTable({ files, displayTimezone }: ProcessedFilesTableProps) {
  const router = useRouter();
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
  const [pendingPath, setPendingPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const removeMarker = async (filePath: string) => {
    const confirmed = window.confirm("Remove this processed marker so the file can be picked up on the next sync?");
    if (!confirmed) {
      return;
    }

    setPendingPath(filePath);
    setError(null);
    setFeedback(null);
    try {
      const response = await apiFetchJson<DeleteResponse>(`/processed-files?file_path=${encodeURIComponent(filePath)}`, {
        method: "DELETE",
        cache: "no-store",
      });
      setFeedback(response.deleted ? "Processed marker removed." : "No matching processed marker was found.");
      router.refresh();
    } catch (err) {
      setError(buildErrorMessage(err));
    } finally {
      setPendingPath(null);
    }
  };

  return (
    <>
      {feedback && <p className="muted table-feedback">{feedback}</p>}
      {error && <p className="error-text table-feedback">{error}</p>}
      <div className="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>Processed At</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {files.length === 0 && (
              <tr>
                <td colSpan={3}>No file history yet.</td>
              </tr>
            )}
            {files.map((file) => (
              <tr key={`${file.file_path}-${file.processed_at}`}>
                <td>{file.file_path}</td>
                <td>{formatTimestamp(file.processed_at_iso, timestampFormatter)}</td>
                <td>
                  <button
                    type="button"
                    className="button ghost table-action"
                    disabled={pendingPath === file.file_path}
                    onClick={() => removeMarker(file.file_path)}
                  >
                    {pendingPath === file.file_path ? "Removing..." : "Remove marker"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
