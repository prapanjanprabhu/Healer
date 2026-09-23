"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { Instance } from "@/lib/types";

const POLL_MS = 4000;

function healthLabel(instance: Instance): string {
  if (instance.healthy === null) return "—";
  return instance.healthy ? "healthy" : "unhealthy";
}

export function InstanceTable({ applicationId }: { applicationId: string }) {
  const [instances, setInstances] = useState<Instance[] | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const response = await apiFetch(`/applications/${applicationId}/instances`);
      if (!response.ok || cancelled) return;
      setInstances(await response.json());
    }

    load();
    const interval = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [applicationId]);

  return (
    <div className="healer-card" style={{ maxWidth: 900, marginTop: 20 }}>
      <div className="healer-card-title">Instances</div>
      {!instances || instances.length === 0 ? (
        <p className="healer-card-description">No instances yet.</p>
      ) : (
        <table className="healer-table">
          <thead>
            <tr>
              <th>Port</th>
              <th>Server</th>
              <th>State</th>
              <th>Health</th>
              <th>Response time</th>
              <th>Release</th>
              <th>Failure reason</th>
            </tr>
          </thead>
          <tbody>
            {instances.map((instance) => (
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
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
