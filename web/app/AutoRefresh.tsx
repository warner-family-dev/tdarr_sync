'use client';

import { useAutoRefresh, SyncStatus } from "./hooks/useAutoRefresh";

type Props = {
  initialStatus: SyncStatus | null;
  intervalMs?: number;
};

export default function AutoRefresh({ initialStatus, intervalMs = 5000 }: Props) {
  useAutoRefresh(initialStatus, intervalMs);
  return null;
}
