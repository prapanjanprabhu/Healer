"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useHasPermission } from "@/components/CurrentUserProvider";
import type { DeploymentDetail } from "@/lib/types";

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "rolled_back"]);

export function ScalePanel({
  applicationId,
  minReplicas,
  maxReplicas,
  initialDesiredReplicas,
}: {
  applicationId: string;
  minReplicas: number;
  maxReplicas: number;
  initialDesiredReplicas: number;
}) {
  const canScale = useHasPermission("scale");
  const [target, setTarget] = useState(initialDesiredReplicas);
  const [confirming, setConfirming] = useState(false);
  const [scaling, setScaling] = useState(false);
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

  async function scale() {
    setScaling(true);
    setConfirming(false);
    setError(null);
    const response = await apiFetch(`/applications/${applicationId}/scale`, {
      method: "POST",
      body: JSON.stringify({ desired_replicas: target }),
    });
    setScaling(false);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "Could not start scaling.");
      return;
    }
    const body = await response.json();
    setDeploymentId(body.deployment_id);
    startPolling(body.deployment_id);
  }

  const inProgress = detail !== null && detail.status === "in_progress";
  const outOfRange = target < minReplicas || target > maxReplicas;

  return (
    <div className="healer-card" style={{ maxWidth: 640, marginTop: 20 }}>
      <div className="healer-card-title">Scale</div>
      <p className="healer-card-description" style={{ marginBottom: 12 }}>
        Reserves ports, starts and health-checks new instances before adding them to the gateway,
        or safely drains and stops excess ones. Allowed range: {minReplicas}–{maxReplicas} replicas.
      </p>
      {!canScale ? (
        <p className="healer-card-description">Scaling requires the Operator or Administrator role.</p>
      ) : (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <div className="healer-stepper" role="group" aria-label="Desired replica count">
            <button
              type="button"
              aria-label="Decrease desired replica count"
              onClick={() => {
                setConfirming(false);
                setTarget((t) => Math.max(minReplicas, t - 1));
              }}
              disabled={scaling || inProgress || target <= minReplicas}
            >
              −
            </button>
            <span aria-live="polite" style={{ minWidth: 32, textAlign: "center", display: "inline-block" }}>
              {target}
            </span>
            <button
              type="button"
              aria-label="Increase desired replica count"
              onClick={() => {
                setConfirming(false);
                setTarget((t) => Math.min(maxReplicas, t + 1));
              }}
              disabled={scaling || inProgress || target >= maxReplicas}
            >
              +
            </button>
          </div>

          {!confirming ? (
            <button
              onClick={() => setConfirming(true)}
              disabled={scaling || outOfRange || inProgress || target === initialDesiredReplicas}
            >
              Change to {target}
            </button>
          ) : (
            <>
              <span className="healer-card-description">Apply {target} replica(s)?</span>
              <button onClick={scale} disabled={scaling}>
                {scaling ? "Starting…" : "Confirm"}
              </button>
              <button type="button" onClick={() => setConfirming(false)} disabled={scaling}>
                Cancel
              </button>
            </>
          )}
        </div>
      )}

      {error && (
        <div className="healer-error" style={{ marginTop: 12 }}>
          {error}
        </div>
      )}

      {detail && (
        <div style={{ marginTop: 16 }} aria-live="polite">
          <p className="healer-card-description">
            Scale operation <code>{deploymentId}</code> — status: <strong>{detail.status}</strong>
          </p>
          <ul className="healer-issue-list">
            {detail.steps.map((step, index) => (
              <li
                key={index}
                className={`healer-issue healer-issue-${
                  step.status === "failed"
                    ? "error"
                    : step.status === "skipped"
                      ? "warning"
                      : step.status === "succeeded"
                        ? "success"
                        : "info"
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
