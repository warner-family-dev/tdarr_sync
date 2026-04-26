'use client';

import { useEffect, useMemo, useState } from "react";
import { apiFetchJson } from "./apiClient";
import RoutingSettings from "./RoutingSettings";

type BuildVersion = {
  git_version: string;
  commit_date: string;
  commit_sha: string;
  source: "env" | "git" | "unknown";
};

function buildErrorMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return "Unable to load version details.";
}

export default function SettingsLauncher() {
  const [open, setOpen] = useState(false);
  const [version, setVersion] = useState<BuildVersion | null>(null);
  const [versionError, setVersionError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const payload = await apiFetchJson<BuildVersion>("/version", { cache: "no-store" });
        if (active) {
          setVersion(payload);
          setVersionError(null);
        }
      } catch (error) {
        if (active) {
          setVersion({
            git_version: "unknown",
            commit_date: "unknown",
            commit_sha: "",
            source: "unknown",
          });
          setVersionError(buildErrorMessage(error));
        }
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const versionLabel = useMemo(() => {
    if (!version) {
      return "loading-version";
    }
    return `${version.git_version} (${version.commit_date})`;
  }, [version]);

  return (
    <>
      <div className="settings-launcher">
        <span className="settings-launcher-version">{versionLabel}</span>
        <span className="settings-launcher-sep">|</span>
        <button type="button" className="settings-launcher-link" onClick={() => setOpen(true)}>
          Settings
        </button>
      </div>
      {open && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal settings-modal">
            <div className="modal-header">
              <h3>Settings</h3>
              <button type="button" className="icon-button" onClick={() => setOpen(false)} aria-label="Close settings modal">
                ×
              </button>
            </div>
            <p className="modal-intro">
              <strong>{versionLabel}</strong>
              {version?.commit_sha ? ` · ${version.commit_sha}` : ""}
            </p>
            {versionError && <p className="error-text">{versionError}</p>}
            <div className="modal-section">
              <h4>Tdarr Routing</h4>
              <RoutingSettings />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
