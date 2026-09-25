"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useHasPermission } from "@/components/CurrentUserProvider";
import type { DeploymentDetail } from "@/lib/types";

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "rolled_back"]);

export function DeployPanel({ applicationId }: { applicationId: string }) {
  const canDeploy = useHasPermission("deploy");
  const [confirming, setConfirming] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [deploymentId, setDeploymentId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DeploymentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function startPolling(id: string) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      const response = await apiFetch(`/deployments/${id}`);
      if (!response.ok) return;
      const body: DeploymentDetail = await response.json();
      setDetail(body);
      if (TERMINAL_STATUSES.has(body.status) && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }, 2000);
  }

  async function deploy() {
    setTriggering(true);
    setConfirming(false);
    setError(null);
    const response = await apiFetch(`/applications/${applicationId}/deploy`, { method: "POST" });
    setTriggering(false);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "Could not start the deployment.");
      return;
    }
    const body = await response.json();
    setDeploymentId(body.deployment_id);
    startPolling(body.deployment_id);
  }

  return (
    <div className="healer-card" style={{ maxWidth: 640, marginTop: 20 }}>
      <div className="healer-card-title">Deploy</div>
      <p className="healer-card-description" style={{ marginBottom: 12 }}>
        Snapshots a release, installs requirements, runs migrations and collectstatic, then starts
        one Waitress instance on an automatically allocated port.
      </p>
      {!canDeploy ? (
        <p className="healer-card-description">Deploying requires the Operator or Administrator role.</p>
      ) : !confirming ? (
        <button
          onClick={() => setConfirming(true)}
          disabled={triggering || (detail !== null && detail.status === "in_progress")}
        >
          Deploy
        </button>
      ) : (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span className="healer-card-description">Start a new deployment?</span>
          <button onClick={deploy} disabled={triggering}>
            {triggering ? "Starting…" : "Confirm"}
          </button>
          <button type="button" onClick={() => setConfirming(false)} disabled={triggering}>
            Cancel
          </button>
        </div>
      )}

      {error && <div className="healer-error" style={{ marginTop: 12 }}>{error}</div>}

      {detail && (
        <div style={{ marginTop: 16 }}>
          <p className="healer-card-description">
            Deployment <code>{deploymentId}</code> — status: <strong>{detail.status}</strong>
            {(() => {
              const first = detail.instances[0];
              return (
                first && (
                  <>
                    {" "}
                    · instance <strong>{first.status}</strong> on port <strong>{first.port}</strong>
                    {first.service_name && <> ({first.service_name})</>}
                  </>
                )
              );
            })()}
          </p>
          <ul className="healer-issue-list">
            {detail.steps.map((step, index) => (
              <li
                key={index}
                className={`healer-issue healer-issue-${
                  step.status === "failed" ? "error" : step.status === "skipped" ? "warning" : "info"
                }`}
              >
                <span className="healer-issue-field">{step.name}</span>
                {step.status}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
