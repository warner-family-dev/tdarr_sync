'use client';

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import SyncSelectionModal from "./SyncSelectionModal";
import { apiFetchJson } from "./apiClient";

type TriggerSyncControlProps = {
  disabled: boolean;
};

function buildErrorMessage(error: unknown): string {
  if (typeof error === "string") {
    return error;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Failed to trigger sync.";
}

export default function TriggerSyncControl({ disabled }: TriggerSyncControlProps) {
  const router = useRouter();
  const [dryRun, setDryRun] = useState(false);
  const [useSelection, setUseSelection] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (disabled || pending) {
        return;
      }

      setFeedback(null);
      setError(null);

      if (useSelection) {
        setModalOpen(true);
        return;
      }

      setPending(true);
      try {
        const path = dryRun ? "/sync/run?dry_run=true" : "/sync/run";
        await apiFetchJson(path, { method: "POST", cache: "no-store" });
        setFeedback(dryRun ? "Dry run sync triggered." : "Sync triggered.");
        router.refresh();
      } catch (err) {
        setError(buildErrorMessage(err));
      } finally {
        setPending(false);
      }
    },
    [disabled, dryRun, pending, router, useSelection],
  );

  const handleModalClose = useCallback(() => {
    setModalOpen(false);
  }, []);

  const handleModalCompleted = useCallback(
    (message: string) => {
      setFeedback(message);
      setError(null);
      setModalOpen(false);
      router.refresh();
    },
    [router],
  );

  return (
    <>
      <form className="trigger-form" onSubmit={handleSubmit}>
        <button className="button" type="submit" disabled={disabled || pending}>
          {pending ? "Triggering…" : "Trigger Sync"}
        </button>
        <label className="checkbox">
          <input type="checkbox" checked={dryRun} onChange={(event) => setDryRun(event.target.checked)} />
          Dry run
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={useSelection} onChange={(event) => setUseSelection(event.target.checked)} />
          Select
        </label>
      </form>
      {feedback && <p className="muted">{feedback}</p>}
      {error && <p className="error-text">{error}</p>}
      {modalOpen && (
        <SyncSelectionModal
          dryRun={dryRun}
          onClose={handleModalClose}
          onCompleted={handleModalCompleted}
        />
      )}
    </>
  );
}
