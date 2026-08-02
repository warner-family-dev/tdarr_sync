'use client';

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetchJson } from "./apiClient";

type RouteSource = "sonarr" | "radarr";

type TagFlowRoute = {
  source: RouteSource;
  tag: string;
  tdarr_library_id: string;
  tdarr_library_name: string;
  tdarr_flow_id: string;
  flow_name: string;
  input_subdir: string;
};

type TdarrRoutingTarget = {
  tdarr_library_id: string;
  tdarr_library_name: string;
  tdarr_library_folder: string;
  tdarr_flow_id: string;
  flow_name: string;
  input_subdir: string;
};

type TdarrRoutingTargetsPayload = {
  configured: boolean;
  reachable: boolean;
  error: string | null;
  targets: TdarrRoutingTarget[];
};

type RoutingSettingsPayload = {
  tdarr_server_url: string;
  configured: boolean;
  show_job_error_count: boolean;
  routes: TagFlowRoute[];
};

type RoutingSettingsUpdatePayload = {
  tdarr_server_url: string;
  tdarr_api_key?: string;
  show_job_error_count: boolean;
  routes: Array<Pick<TagFlowRoute, "source" | "tag" | "tdarr_library_id">>;
};

const EMPTY_ROUTE: TagFlowRoute = {
  source: "sonarr",
  tag: "",
  tdarr_library_id: "",
  tdarr_library_name: "",
  tdarr_flow_id: "",
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
  const [targets, setTargets] = useState<TdarrRoutingTarget[]>([]);
  const [targetError, setTargetError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [payload, targetPayload] = await Promise.all([
        apiFetchJson<RoutingSettingsPayload>("/settings/routing", { cache: "no-store" }),
        apiFetchJson<TdarrRoutingTargetsPayload>("/settings/routing/targets", { cache: "no-store" }),
      ]);
      setSettings({
        tdarr_server_url: payload.tdarr_server_url ?? "",
        configured: Boolean(payload.configured),
        show_job_error_count: Boolean(payload.show_job_error_count),
        routes: Array.isArray(payload.routes)
          ? payload.routes.map((route) => ({
              source: route.source,
              tag: route.tag ?? "",
              tdarr_library_id: route.tdarr_library_id ?? "",
              tdarr_library_name: route.tdarr_library_name ?? "",
              tdarr_flow_id: route.tdarr_flow_id ?? "",
              flow_name: route.flow_name ?? "",
              input_subdir: route.input_subdir ?? "",
            }))
          : [],
      });
      setTargets(Array.isArray(targetPayload.targets) ? targetPayload.targets : []);
      setTargetError(targetPayload.reachable ? null : targetPayload.error ?? "Unable to load Tdarr libraries.");
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

  const targetsById = useMemo(
    () => new Map(targets.map((target) => [target.tdarr_library_id, target])),
    [targets],
  );

  const canSave = useMemo(() => {
    if (saving || loading) {
      return false;
    }
    return settings.routes.every(
      (route) => route.tag.trim().length > 0 && route.tdarr_library_id.trim().length > 0,
    );
  }, [saving, loading, settings.routes]);

  const handleSubmit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!canSave) {
        setError("Each route needs a tag and Tdarr library.");
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
            tdarr_library_id: route.tdarr_library_id.trim(),
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
        Route order matters. The first matching tag per source wins. Choose a Tdarr library; its linked flow and input
        folder are loaded directly from Tdarr. Files are grouped as Source/Tdarr-library-folder/title.
      </p>

      {targetError && <p className="error-text">{targetError}</p>}

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
              <span>Tdarr library / flow</span>
              <select
                value={route.tdarr_library_id}
                onChange={(event) => updateRoute(index, "tdarr_library_id", event.target.value)}
              >
                <option value="">Select a Tdarr library</option>
                {route.tdarr_library_id && !targetsById.has(route.tdarr_library_id) && (
                  <option value={route.tdarr_library_id}>
                    {route.tdarr_library_name || "Unavailable Tdarr library"}
                  </option>
                )}
                {targets.map((target) => (
                  <option key={target.tdarr_library_id} value={target.tdarr_library_id}>
                    {target.tdarr_library_name} — {target.flow_name}
                  </option>
                ))}
              </select>
              <span className="muted">
                Destination: {route.source === "sonarr" ? "Sonarr" : "Radarr"}/
                {targetsById.get(route.tdarr_library_id)?.input_subdir || route.input_subdir || "…"}
                {" · Flow: "}
                {targetsById.get(route.tdarr_library_id)?.flow_name || route.flow_name || "…"}
              </span>
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
