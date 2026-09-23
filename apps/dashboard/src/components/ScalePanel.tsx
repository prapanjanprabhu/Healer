"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
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
  const [target, setTarget] = useState(initialDesiredReplicas);
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

  return (
    <div className="healer-card" style={{ maxWidth: 640, marginTop: 20 }}>
      <div className="healer-card-title">Scale</div>
      <p className="healer-card-description" style={{ marginBottom: 12 }}>
        Reserves ports, starts and health-checks new instances before adding them to the gateway,
        or safely drains and stops excess ones. Allowed range: {minReplicas}–{maxReplicas} replicas.
      </p>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          type="number"
          min={minReplicas}
          max={maxReplicas}
          value={target}
          onChange={(e) => setTarget(Number(e.target.value))}
          style={{ width: 80 }}
        />
        <button
          onClick={scale}
          disabled={
            scaling ||
            target < minReplicas ||
            target > maxReplicas ||
            (detail !== null && detail.status === "in_progress")
          }
        >
          {scaling ? "Starting…" : "Scale"}
        </button>
      </div>

      {error && (
        <div className="healer-error" style={{ marginTop: 12 }}>
          {error}
        </div>
      )}

      {detail && (
        <div style={{ marginTop: 16 }}>
          <p className="healer-card-description">
            Scale operation <code>{deploymentId}</code> — status: <strong>{detail.status}</strong>
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
