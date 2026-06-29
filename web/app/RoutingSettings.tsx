'use client';

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetchJson } from "./apiClient";

type RouteSource = "sonarr" | "radarr";

type TagFlowRoute = {
  source: RouteSource;
  tag: string;
  flow_name: string;
  input_subdir: string;
};

type RoutingSettingsPayload = {
  tdarr_server_url: string;
  configured: boolean;
  show_job_error_count: boolean;
  routes: TagFlowRoute[];
};

type RoutingSettingsUpdatePayload = Omit<RoutingSettingsPayload, "configured"> & {
  tdarr_api_key?: string;
};

const EMPTY_ROUTE: TagFlowRoute = {
  source: "sonarr",
  tag: "",
  flow_name: "",
  input_subdir: "",
};

function buildErrorMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return "Failed to load or save routing settings.";
}

export default function RoutingSettings() {
  const [settings, setSettings] = useState<RoutingSettingsPayload>({
    tdarr_server_url: "",
    configured: false,
    show_job_error_count: false,
    routes: [],
  });
  const [tdarrApiKey, setTdarrApiKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await apiFetchJson<RoutingSettingsPayload>("/settings/routing", { cache: "no-store" });
      setSettings({
        tdarr_server_url: payload.tdarr_server_url ?? "",
        configured: Boolean(payload.configured),
        show_job_error_count: Boolean(payload.show_job_error_count),
        routes: Array.isArray(payload.routes)
          ? payload.routes.map((route) => ({
              source: route.source,
              tag: route.tag ?? "",
              flow_name: route.flow_name ?? "",
              input_subdir: route.input_subdir ?? "",
            }))
          : [],
      });
      setTdarrApiKey("");
    } catch (err) {
      setError(buildErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const updateRoute = useCallback((index: number, field: keyof TagFlowRoute, value: string) => {
    setSettings((prev) => {
      const routes = [...prev.routes];
      const target = routes[index];
      if (!target) {
        return prev;
      }
      routes[index] = { ...target, [field]: value };
      return { ...prev, routes };
    });
  }, []);

  const addRoute = useCallback(() => {
    setSettings((prev) => ({ ...prev, routes: [...prev.routes, { ...EMPTY_ROUTE }] }));
  }, []);

  const removeRoute = useCallback((index: number) => {
    setSettings((prev) => {
      const routes = prev.routes.filter((_, idx) => idx !== index);
      return { ...prev, routes };
    });
  }, []);

  const moveRoute = useCallback((index: number, direction: -1 | 1) => {
    setSettings((prev) => {
      const target = index + direction;
      if (target < 0 || target >= prev.routes.length) {
        return prev;
      }
      const routes = [...prev.routes];
      const current = routes[index];
      routes[index] = routes[target];
      routes[target] = current;
      return { ...prev, routes };
    });
  }, []);

  const canSave = useMemo(() => {
    if (saving || loading) {
      return false;
    }
    return settings.routes.every((route) => route.tag.trim().length > 0 && route.flow_name.trim().length > 0);
  }, [saving, loading, settings.routes]);

  const handleSubmit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!canSave) {
        setError("Each route needs a tag and flow name.");
        return;
      }

      setSaving(true);
      setError(null);
      setFeedback(null);
      try {
        const payload: RoutingSettingsUpdatePayload = {
          tdarr_server_url: settings.tdarr_server_url.trim(),
          show_job_error_count: settings.show_job_error_count,
          routes: settings.routes.map((route) => ({
            source: route.source,
            tag: route.tag.trim(),
            flow_name: route.flow_name.trim(),
            input_subdir: route.input_subdir.trim(),
          })),
        };
        if (tdarrApiKey.trim()) {
          payload.tdarr_api_key = tdarrApiKey.trim();
        }
        const saved = await apiFetchJson<RoutingSettingsPayload>("/settings/routing", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        setSettings({
          tdarr_server_url: saved.tdarr_server_url ?? "",
          configured: Boolean(saved.configured),
          show_job_error_count: Boolean(saved.show_job_error_count),
          routes: saved.routes ?? [],
        });
        setTdarrApiKey("");
        setFeedback("Routing settings saved.");
      } catch (err) {
        setError(buildErrorMessage(err));
      } finally {
        setSaving(false);
      }
    },
    [canSave, settings, tdarrApiKey],
  );

  if (loading) {
    return <p className="muted">Loading routing settings…</p>;
  }

  return (
    <form className="routing-form" onSubmit={handleSubmit}>
      <div className="routing-grid">
        <label className="form-field">
          <span>Tdarr server URL</span>
          <input
            type="text"
            placeholder="http://192.168.1.50:8266"
            value={settings.tdarr_server_url}
            onChange={(event) => setSettings((prev) => ({ ...prev, tdarr_server_url: event.target.value }))}
          />
        </label>
        <label className="form-field">
          <span>Tdarr API key</span>
          <input
            type="password"
            placeholder={settings.configured ? "Configured — enter a new key to replace" : "tapi_..."}
            value={tdarrApiKey}
            onChange={(event) => setTdarrApiKey(event.target.value)}
          />
        </label>
      </div>

      <label className="checkbox-inline">
        <input
          type="checkbox"
          checked={settings.show_job_error_count}
          onChange={(event) =>
            setSettings((prev) => ({ ...prev, show_job_error_count: event.target.checked }))
          }
        />
        <span>Show historical Tdarr job error total</span>
      </label>

      <p className="muted">
        Route order matters. The first matching tag per source wins, and files are copied into the configured Tdarr
        input subfolder.
      </p>

      <div className="routing-list">
        {settings.routes.length === 0 && <p className="muted">No routes configured.</p>}
        {settings.routes.map((route, index) => (
          <div key={`${route.source}-${index}`} className="routing-row">
            <label className="form-field compact">
              <span>Source</span>
              <select
                value={route.source}
                onChange={(event) => updateRoute(index, "source", event.target.value as RouteSource)}
              >
                <option value="sonarr">Sonarr</option>
                <option value="radarr">Radarr</option>
              </select>
            </label>
            <label className="form-field compact">
              <span>Tag</span>
              <input type="text" value={route.tag} onChange={(event) => updateRoute(index, "tag", event.target.value)} />
            </label>
            <label className="form-field compact">
              <span>Flow name</span>
              <input
                type="text"
                value={route.flow_name}
                onChange={(event) => updateRoute(index, "flow_name", event.target.value)}
              />
            </label>
            <label className="form-field compact">
              <span>Input subdir</span>
              <input
                type="text"
                value={route.input_subdir}
                placeholder="auto-from-flow-name"
                onChange={(event) => updateRoute(index, "input_subdir", event.target.value)}
              />
            </label>
            <div className="routing-actions">
              <button type="button" className="button ghost" onClick={() => moveRoute(index, -1)} disabled={index === 0}>
                ↑
              </button>
              <button
                type="button"
                className="button ghost"
                onClick={() => moveRoute(index, 1)}
                disabled={index >= settings.routes.length - 1}
              >
                ↓
              </button>
              <button type="button" className="button ghost" onClick={() => removeRoute(index)}>
                Remove
              </button>
            </div>
          </div>
        ))}
      </div>

      {feedback && <p className="muted">{feedback}</p>}
      {error && <p className="error-text">{error}</p>}

      <div className="form-actions">
        <button type="button" className="button secondary" onClick={addRoute}>
          Add Route
        </button>
        <button type="submit" className="button" disabled={!canSave}>
          {saving ? "Saving…" : "Save Routing"}
        </button>
      </div>
    </form>
  );
}
