"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { DeploymentTimeline } from "@/components/DeploymentTimeline";
import type { DeploymentDetail } from "@/lib/types";

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "rolled_back"]);

/** Live-polls a deployment while it's in progress, otherwise just shows the
 * final state — the standalone Deployment Details page's client half.
 */
export function DeploymentDetailView({ initialDetail }: { initialDetail: DeploymentDetail }) {
  const [detail, setDetail] = useState(initialDetail);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (TERMINAL_STATUSES.has(detail.status)) return;
    pollRef.current = setInterval(async () => {
      const response = await apiFetch(`/deployments/${initialDetail.id}`);
      if (!response.ok) return;
      const body: DeploymentDetail = await response.json();
      setDetail(body);
      if (TERMINAL_STATUSES.has(body.status) && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialDetail.id]);

  return (
    <div aria-live="polite">
      <DeploymentTimeline detail={detail} />
      {detail.instances.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div className="healer-card-title">Instances touched</div>
          <ul className="healer-issue-list">
            {detail.instances.map((instance) => (
              <li key={instance.id} className="healer-issue healer-issue-info">
                <span className="healer-issue-field">port {instance.port}</span>
                {instance.status} {instance.service_name ? `(${instance.service_name})` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
      {detail.logs.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div className="healer-card-title">Log</div>
          <pre
            style={{
              maxHeight: 260,
              overflowY: "auto",
              background: "var(--healer-code-bg, #111)",
              color: "var(--healer-code-fg, #ddd)",
              padding: 12,
              borderRadius: 6,
              fontSize: 12,
              whiteSpace: "pre-wrap",
            }}
          >
            {detail.logs.map((l) => `[${l.level}] ${l.message}`).join("\n")}
          </pre>
        </div>
      )}
    </div>
  );
}
