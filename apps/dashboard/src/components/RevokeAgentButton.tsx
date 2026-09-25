"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { useHasPermission } from "@/components/CurrentUserProvider";

/** Force-disconnects this server's Agent and invalidates its credential —
 * for a decommissioned server or a suspected-compromised credential.
 * Re-enrolling (a fresh token from EnrollmentTokenPanel) works exactly
 * like first-time enrollment afterward.
 */
export function RevokeAgentButton({ serverId }: { serverId: string }) {
  const canManage = useHasPermission("manage_servers");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!canManage) return null;

  async function revoke() {
    if (
      !confirm(
        "Revoke this server's Agent credential? It will be disconnected immediately and must be re-enrolled with a new token before it can reconnect."
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    const response = await apiFetch(`/servers/${serverId}/agent/revoke`, { method: "POST" });
    setBusy(false);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "Could not revoke the agent.");
      return;
    }
    router.refresh();
  }

  return (
    <div style={{ marginTop: 8 }}>
      <button className="healer-btn-danger" onClick={revoke} disabled={busy}>
        {busy ? "Revoking…" : "Revoke agent"}
      </button>
      {error && (
        <div className="healer-error" style={{ marginTop: 8 }}>
          {error}
        </div>
      )}
    </div>
  );
}
