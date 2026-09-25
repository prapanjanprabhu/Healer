"use client";

import type { DeploymentDetail } from "@/lib/types";

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString();
}

function durationLabel(started: string | null, finished: string | null): string {
  if (!started || !finished) return "";
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  if (ms < 0) return "";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

const STEP_CLASS: Record<string, string> = {
  succeeded: "healer-issue-success",
  failed: "healer-issue-error",
  skipped: "healer-issue-warning",
};

/** A chronological view of one deployment's steps — used for a plain deploy,
 * a scale operation, or a blue-green release switch/rollback (Phase 11's
 * "deployment timeline"). `detail.kind` and `detail.failure_reason` (both
 * added in Phase 11) label what happened and why, if it didn't succeed.
 */
export function DeploymentTimeline({ detail }: { detail: DeploymentDetail }) {
  return (
    <div>
      <p className="healer-card-description">
        <span className="healer-badge">{detail.kind}</span> — status: <strong>{detail.status}</strong>
      </p>
      {detail.failure_reason && (
        <div className="healer-error" style={{ marginTop: 8 }}>
          {detail.failure_reason}
        </div>
      )}
      <ol style={{ listStyle: "none", padding: 0, marginTop: 12 }}>
        {detail.steps.map((step, index) => (
          <li
            key={index}
            className={`healer-issue ${STEP_CLASS[step.status] ?? "healer-issue-info"}`}
            style={{ display: "flex", justifyContent: "space-between", gap: 12 }}
          >
            <span>
              <span className="healer-issue-field">{step.name}</span>
              {step.status}
            </span>
            <span style={{ color: "var(--healer-muted, #888)", flexShrink: 0 }}>
              {formatTime(step.started_at)}
              {durationLabel(step.started_at, step.finished_at) &&
                ` (${durationLabel(step.started_at, step.finished_at)})`}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
