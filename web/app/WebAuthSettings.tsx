"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetchJson } from "./apiClient";

type WebAuthSettingsPayload = {
  enabled: boolean;
  trust_proxy_headers: boolean;
  trusted_networks: string[];
};

const DEFAULT_SETTINGS: WebAuthSettingsPayload = {
  enabled: false,
  trust_proxy_headers: false,
  trusted_networks: [],
};

function buildErrorMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return "Failed to load or save dashboard access settings.";
}

function splitNetworks(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map((network) => network.trim())
    .filter(Boolean);
}

export default function WebAuthSettings() {
  const [settings, setSettings] = useState<WebAuthSettingsPayload>(DEFAULT_SETTINGS);
  const [networkText, setNetworkText] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await apiFetchJson<WebAuthSettingsPayload>("/settings/web-auth", { cache: "no-store" });
      const normalized = {
        enabled: Boolean(payload.enabled),
        trust_proxy_headers: Boolean(payload.trust_proxy_headers),
        trusted_networks: Array.isArray(payload.trusted_networks) ? payload.trusted_networks : [],
      };
      setSettings(normalized);
      setNetworkText(normalized.trusted_networks.join("\n"));
    } catch (err) {
      setError(buildErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const networks = useMemo(() => splitNetworks(networkText), [networkText]);
  const canSave = !loading && !saving && (!settings.enabled || (settings.trust_proxy_headers && networks.length > 0));

  const handleSubmit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!canSave) {
        setError("Enable trusted proxy headers and enter at least one CIDR before enabling login bypass.");
        return;
      }

      setSaving(true);
      setError(null);
      setFeedback(null);
      try {
        const saved = await apiFetchJson<WebAuthSettingsPayload>("/settings/web-auth", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            enabled: settings.enabled,
            trust_proxy_headers: settings.trust_proxy_headers,
            trusted_networks: networks,
          }),
        });
        setSettings(saved);
        setNetworkText(saved.trusted_networks.join("\n"));
        setFeedback("Dashboard access settings saved. New requests use them immediately.");
      } catch (err) {
        setError(buildErrorMessage(err));
      } finally {
        setSaving(false);
      }
    },
    [canSave, networks, settings.enabled, settings.trust_proxy_headers],
  );

  if (loading) return <p className="muted">Loading dashboard access settings…</p>;

  return (
    <form className="routing-form" onSubmit={handleSubmit}>
      <label className="checkbox-inline">
        <input
          type="checkbox"
          checked={settings.enabled}
          onChange={(event) => setSettings((previous) => ({ ...previous, enabled: event.target.checked }))}
        />
        <span>Skip dashboard login for trusted networks</span>
      </label>

      <label className="checkbox-inline">
        <input
          type="checkbox"
          checked={settings.trust_proxy_headers}
          onChange={(event) =>
            setSettings((previous) => ({ ...previous, trust_proxy_headers: event.target.checked }))
          }
        />
        <span>Trust client IP headers from Traefik or Cloudflare</span>
      </label>

      <label className="form-field">
        <span>Trusted network CIDRs</span>
        <textarea
          rows={4}
          value={networkText}
          placeholder={"192.168.4.0/24\n10.0.0.0/8"}
          onChange={(event) => setNetworkText(event.target.value)}
          spellCheck={false}
        />
      </label>

      <p className="muted">
        Enter one IPv4 or IPv6 CIDR per line. Only enable proxy headers when all traffic reaches this dashboard through
        a trusted proxy that overwrites forwarded-IP headers. Keep port 3001 firewalled from untrusted clients.
      </p>
      <p className="muted">
        Cloudflare-proxied requests normally carry the browser&apos;s public IP, not its private LAN address. Use split
        DNS for local Traefik access, or explicitly trust the appropriate public /32 only when that address is stable.
      </p>

      {feedback && <p className="muted">{feedback}</p>}
      {error && <p className="error-text">{error}</p>}

      <div className="form-actions">
        <button type="submit" className="button" disabled={!canSave}>
          {saving ? "Saving…" : "Save Dashboard Access"}
        </button>
      </div>
    </form>
  );
}
