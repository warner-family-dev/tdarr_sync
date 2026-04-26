'use client';

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { apiFetchJson } from "../apiClient";

export type SyncStatus = {
  running: boolean;
  last_started_at: number | null;
  last_started_at_iso?: string | null;
  last_finished_at: number | null;
  last_finished_at_iso?: string | null;
  last_exit_code: number | null;
  last_error: string | null;
  progress?: unknown;
  tdarr?: unknown;
};

const serialize = (status: SyncStatus | null) => JSON.stringify(status ?? {});

export function useAutoRefresh(initialStatus: SyncStatus | null, intervalMs = 5000) {
  const router = useRouter();
  const statusRef = useRef<string>(serialize(initialStatus));

  useEffect(() => {
    statusRef.current = serialize(initialStatus);
  }, [initialStatus]);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const nextStatus = await apiFetchJson<SyncStatus>("/sync/status", { cache: "no-store" });
        const serialized = serialize(nextStatus);
        if (!cancelled && serialized !== statusRef.current) {
          statusRef.current = serialized;
          router.refresh();
        }
      } catch {
        // Intentionally ignore transient errors; next interval will retry.
      }
    };

    const id = setInterval(poll, intervalMs);
    poll();

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [intervalMs, router]);
}
