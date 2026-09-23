"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { DeploymentDetail } from "@/lib/types";

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "rolled_back"]);

export function DeployPanel({ applicationId }: { applicationId: string }) {
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
      <button onClick={deploy} disabled={triggering || (detail !== null && detail.status === "in_progress")}>
        {triggering ? "Starting…" : "Deploy"}
      </button>

      {error && <div className="healer-error" style={{ marginTop: 12 }}>{error}</div>}

      {detail && (
        <div style={{ marginTop: 16 }}>
          <p className="healer-card-description">
            Deployment <code>{deploymentId}</code> — status: <strong>{detail.status}</strong>
            {detail.instance && (
              <>
                {" "}
                · instance <strong>{detail.instance.status}</strong> on port{" "}
                <strong>{detail.instance.port}</strong>
                {detail.instance.service_name && <> ({detail.instance.service_name})</>}
              </>
            )}
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
