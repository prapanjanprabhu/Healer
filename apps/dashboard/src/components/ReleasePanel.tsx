"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useHasPermission } from "@/components/CurrentUserProvider";
import { DeploymentTimeline } from "@/components/DeploymentTimeline";
import type { DeploymentDetail, Release } from "@/lib/types";

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "rolled_back"]);
type Confirming = "deploy" | "rollback" | null;

export function ReleasePanel({ applicationId }: { applicationId: string }) {
  const canDeploy = useHasPermission("deploy");
  const canRollback = useHasPermission("rollback");
  const [releases, setReleases] = useState<Release[]>([]);
  const [selectedRelease, setSelectedRelease] = useState("");
  const [confirming, setConfirming] = useState<Confirming>(null);
  const [busy, setBusy] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [detail, setDetail] = useState<DeploymentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function loadReleases() {
    const response = await apiFetch(`/applications/${applicationId}/releases`);
    if (response.ok) setReleases(await response.json());
  }

  useEffect(() => {
    loadReleases();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicationId]);

  function startPolling(deploymentId: string) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      const response = await apiFetch(`/deployments/${deploymentId}`);
      if (!response.ok) return;
      const body: DeploymentDetail = await response.json();
      setDetail(body);
      if (TERMINAL_STATUSES.has(body.status) && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
        loadReleases();
        // The just-rolled-back-to release is now active and drops out of
        // rollbackCandidates, but the <select> would otherwise keep
        // showing its stale id as "selected" — leaving the Roll back
        // button enabled for a release_id that's no longer a valid
        // candidate instead of naturally disabling via !selectedRelease.
        setSelectedRelease("");
      }
    }, 2000);
  }

  async function deployNewRelease() {
    setBusy(true);
    setConfirming(null);
    setError(null);
    setWarnings([]);
    const response = await apiFetch(`/applications/${applicationId}/releases`, { method: "POST" });
    setBusy(false);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "Could not start the release switch.");
      return;
    }
    const body = await response.json();
    setWarnings(body.warnings ?? []);
    startPolling(body.deployment_id);
  }

  async function rollback() {
    if (!selectedRelease) return;
    setBusy(true);
    setConfirming(null);
    setError(null);
    setWarnings([]);
    const response = await apiFetch(`/applications/${applicationId}/rollback`, {
      method: "POST",
      body: JSON.stringify({ release_id: selectedRelease }),
    });
    setBusy(false);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "Could not start the rollback.");
      return;
    }
    const body = await response.json();
    startPolling(body.deployment_id);
  }

  const rollbackCandidates = releases.filter((r) => !r.is_active && r.status === "ready");
  const inProgress = detail !== null && detail.status === "in_progress";

  return (
    <div className="healer-card" style={{ maxWidth: 720, marginTop: 20 }}>
      <div className="healer-card-title">Releases</div>
      <p className="healer-card-description" style={{ marginBottom: 12 }}>
        Blue-green update: builds a new release, health-gates it on freshly reserved ports, then
        atomically switches Nginx — the current release keeps serving until the new one proves
        healthy. See docs/blue-green-deployment.md.
      </p>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        {canDeploy && (
          <>
            {confirming !== "deploy" ? (
              <button onClick={() => setConfirming("deploy")} disabled={busy || inProgress}>
                Deploy new release
              </button>
            ) : (
              <>
                <span className="healer-card-description">Start a new release switch?</span>
                <button onClick={deployNewRelease} disabled={busy}>
                  {busy ? "Starting…" : "Confirm"}
                </button>
                <button type="button" onClick={() => setConfirming(null)} disabled={busy}>
                  Cancel
                </button>
              </>
            )}
          </>
        )}

        {canRollback && (
          <>
            <select
              value={selectedRelease}
              onChange={(e) => {
                setSelectedRelease(e.target.value);
                setConfirming(null);
              }}
              disabled={rollbackCandidates.length === 0 || confirming === "rollback"}
            >
              <option value="">
                {rollbackCandidates.length === 0 ? "No previous release available" : "Roll back to…"}
              </option>
              {rollbackCandidates.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.ref} ({new Date(r.created_at).toLocaleString()})
                </option>
              ))}
            </select>
            {confirming !== "rollback" ? (
              <button
                onClick={() => setConfirming("rollback")}
                disabled={busy || inProgress || !selectedRelease}
              >
                Roll back
              </button>
            ) : (
              <>
                <span className="healer-card-description">Roll back to the selected release?</span>
                <button onClick={rollback} disabled={busy}>
                  {busy ? "Starting…" : "Confirm"}
                </button>
                <button type="button" onClick={() => setConfirming(null)} disabled={busy}>
                  Cancel
                </button>
              </>
            )}
          </>
        )}

        {!canDeploy && !canRollback && (
          <p className="healer-card-description">
            Deploying and rolling back require the Operator or Administrator role.
          </p>
        )}
      </div>

      {error && (
        <div className="healer-error" style={{ marginTop: 12 }}>
          {error}
        </div>
      )}
      {warnings.map((w, i) => (
        <div key={i} className="healer-issue healer-issue-warning" style={{ marginTop: 12 }}>
          {w}
        </div>
      ))}

      {releases.length > 0 && (
        <ul className="healer-issue-list" style={{ marginTop: 12 }}>
          {releases.map((r) => (
            <li key={r.id} className={`healer-issue healer-issue-${r.is_active ? "info" : "warning"}`}>
              <span className="healer-issue-field">{r.ref}</span>
              {r.status}
              {r.is_active && " (active)"}
            </li>
          ))}
        </ul>
      )}

      {detail && (
        <div style={{ marginTop: 16 }}>
          <DeploymentTimeline detail={detail} />
        </div>
      )}
    </div>
  );
}
