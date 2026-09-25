"use client";

import { useState } from "react";
import { apiFetch } from "@/lib/api";
import { useHasPermission } from "@/components/CurrentUserProvider";
import type { GatewaySyncResponse } from "@/lib/types";

export function GatewayPanel({
  applicationId,
  hostname,
}: {
  applicationId: string;
  hostname: string;
}) {
  const canSync = useHasPermission("deploy");
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState<GatewaySyncResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function sync() {
    setSyncing(true);
    setError(null);
    const response = await apiFetch(`/applications/${applicationId}/gateway/sync`, {
      method: "POST",
    });
    setSyncing(false);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "Could not reach the Control Plane.");
      return;
    }
    setResult(await response.json());
  }

  return (
    <div className="healer-card" style={{ maxWidth: 640, marginTop: 20 }}>
      <div className="healer-card-title">Gateway routing</div>
      <p className="healer-card-description" style={{ marginBottom: 12 }}>
        Routes <code>{hostname}</code> through the central Nginx gateway to this
        application&apos;s currently healthy instance. Runs automatically after each
        successful deploy — use this to re-sync without deploying again.
      </p>
      {canSync ? (
        <button onClick={sync} disabled={syncing}>
          {syncing ? "Syncing…" : "Sync gateway"}
        </button>
      ) : (
        <p className="healer-card-description">Syncing requires the Operator or Administrator role.</p>
      )}

      {error && (
        <div className="healer-error" style={{ marginTop: 12 }}>
          {error}
        </div>
      )}

      {result && (
        <p
          className={`healer-issue healer-issue-${result.ok ? "success" : "error"}`}
          style={{ marginTop: 12 }}
        >
          {result.message || (result.ok ? "Synced." : "Sync failed.")}
        </p>
      )}
    </div>
  );
}
