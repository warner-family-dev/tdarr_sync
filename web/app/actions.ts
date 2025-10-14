"use server";

import { revalidatePath } from "next/cache";

import { apiFetch } from "./apiClient";

export async function triggerSyncAction(formData: FormData) {
  const dryRun = formData.get("dry-run") === "on" || formData.get("dry-run") === "true";
  const query = dryRun ? "?dry_run=true" : "";

  try {
    const res = await apiFetch(`/sync/run${query}`, { method: "POST", cache: "no-store" });
    if (!res.ok && res.status !== 409) {
      throw new Error(`Sync trigger failed: ${res.status} ${res.statusText}`);
    }
  } catch (error) {
    console.error(error);
  }

  revalidatePath("/");
}
