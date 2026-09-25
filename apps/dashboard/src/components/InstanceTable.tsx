"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useHasPermission } from "@/components/CurrentUserProvider";
import type { Instance } from "@/lib/types";

const POLL_MS = 4000;
const ACTIONABLE_STATUSES = new Set(["running", "unhealthy"]);

function healthLabel(instance: Instance): string {
  if (instance.healthy === null) return "—";
  return instance.healthy ? "healthy" : "unhealthy";
}

export function InstanceTable({ applicationId }: { applicationId: string }) {
  const canRestart = useHasPermission("restart");
  const canStop = useHasPermission("stop");
  const [instances, setInstances] = useState<Instance[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const response = await apiFetch(`/applications/${applicationId}/instances`);
    if (!response.ok) return;
    setInstances(await response.json());
  }

  useEffect(() => {
    let cancelled = false;
    async function loadOnce() {
      if (!cancelled) await load();
    }
    loadOnce();
    const interval = setInterval(loadOnce, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicationId]);

  async function act(instance: Instance, action: "restart" | "stop") {
    const verb = action === "restart" ? "Restart" : "Stop";
    if (!confirm(`${verb} the instance on port ${instance.port}?`)) return;
    setBusyId(instance.id);
    setError(null);
    const response = await apiFetch(`/applications/${applicationId}/instances/${instance.id}/${action}`, {
      method: "POST",
    });
    setBusyId(null);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : `Could not ${action} that instance.`);
    }
    load();
  }

  const showActions = canRestart || canStop;

  return (
    <div className="healer-card" style={{ maxWidth: 900, marginTop: 20 }}>
      <div className="healer-card-title">Instances</div>
      {error && (
        <div className="healer-error" style={{ marginBottom: 12 }}>
          {error}
        </div>
      )}
      {!instances || instances.length === 0 ? (
        <p className="healer-card-description">No instances yet.</p>
      ) : (
        <table className="healer-table">
          <caption className="healer-visually-hidden">Application instances and their health</caption>
          <thead>
            <tr>
              <th>Port</th>
              <th>Server</th>
              <th>State</th>
              <th>Health</th>
              <th>Response time</th>
              <th>Release</th>
              <th>Failure reason</th>
              {showActions && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {instances.map((instance) => {
              const actionable = ACTIONABLE_STATUSES.has(instance.status);
              return (
                <tr key={instance.id}>
                  <td>{instance.port}</td>
                  <td>{instance.server_name}</td>
                  <td>{instance.status}</td>
                  <td>{healthLabel(instance)}</td>
                  <td>{instance.response_time_ms !== null ? `${instance.response_time_ms} ms` : "—"}</td>
                  <td>{instance.release_version || "—"}</td>
                  <td>
                    {instance.failure_reason
                      ? `${instance.failure_reason}${instance.healing_attempts ? ` (attempt ${instance.healing_attempts})` : ""}`
                      : "—"}
                  </td>
                  {showActions && (
                    <td style={{ display: "flex", gap: 6 }}>
                      {canRestart && (
                        <button
                          onClick={() => act(instance, "restart")}
                          disabled={!actionable || busyId === instance.id}
                        >
                          Restart
                        </button>
                      )}
                      {canStop && (
                        <button
                          className="healer-btn-danger"
                          onClick={() => act(instance, "stop")}
                          disabled={!actionable || busyId === instance.id}
                        >
                          Stop
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
