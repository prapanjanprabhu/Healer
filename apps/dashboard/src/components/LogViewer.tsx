"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { CONTROL_PLANE_URL } from "@/lib/config";
import type { DeploymentSummary, LogChunk, LogSource } from "@/lib/types";

const SEVERITY_HINTS = ["error", "warn", "info", "debug"] as const;

function detectSeverity(line: string): string | null {
  const lower = line.toLowerCase();
  for (const level of SEVERITY_HINTS) {
    if (lower.includes(level)) return level;
  }
  return null;
}

/** Log source registry + safe bounded view + live tail (Phase 12). Lists
 * every instance's stdout/stderr plus a pointer at this application's
 * deployment logs, fetches a bounded recent chunk, and can switch to a
 * live SSE tail — all server-redacted before it ever reaches this component.
 */
export function LogViewer({ applicationId }: { applicationId: string }) {
  const [sources, setSources] = useState<LogSource[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [chunk, setChunk] = useState<LogChunk | null>(null);
  const [deployments, setDeployments] = useState<DeploymentSummary[]>([]);
  const [filter, setFilter] = useState("");
  const [severity, setSeverity] = useState("");
  const [live, setLive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const linesRef = useRef<string[]>([]);
  const [, forceRender] = useState(0);

  useEffect(() => {
    apiFetch(`/applications/${applicationId}/log-sources`).then(async (response) => {
      if (!response.ok) return;
      const body: LogSource[] = await response.json();
      setSources(body);
      if (body[0]) setSelected(body[0].id);
    });
  }, [applicationId]);

  const source = sources.find((s) => s.id === selected) ?? null;

  function stopLive() {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    setLive(false);
  }

  async function loadOnce() {
    if (!source || source.type === "deployment") return;
    setError(null);
    const response = await apiFetch(
      `/applications/${applicationId}/instances/${source.instance_id}/logs?stream=${source.type}`
    );
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "Could not load this log.");
      setChunk(null);
      return;
    }
    const body: LogChunk = await response.json();
    linesRef.current = body.lines;
    setChunk(body);
  }

  useEffect(() => {
    stopLive();
    linesRef.current = [];
    setChunk(null);
    setError(null);
    if (source && source.type === "deployment") {
      apiFetch("/deployments").then(async (response) => {
        if (response.ok) {
          const all: DeploymentSummary[] = await response.json();
          setDeployments(all.filter((d) => d.application_id === applicationId));
        }
      });
    } else if (source) {
      loadOnce();
    }
    return stopLive;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  function startLive() {
    if (!source || source.type === "deployment") return;
    setLive(true);
    const url = `${CONTROL_PLANE_URL}/applications/${applicationId}/instances/${source.instance_id}/logs/stream?stream=${source.type}`;
    const es = new EventSource(url, { withCredentials: true });
    eventSourceRef.current = es;
    es.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.lines) {
        linesRef.current = [...linesRef.current, ...payload.lines].slice(-2000);
        forceRender((n) => n + 1);
      }
      if (payload.error) setError(payload.error);
      if (payload.closed) stopLive();
    };
    es.onerror = () => {
      stopLive();
    };
  }

  const displayLines = linesRef.current.filter((line) => {
    if (filter && !line.toLowerCase().includes(filter.toLowerCase())) return false;
    if (severity) {
      const detected = detectSeverity(line);
      if (detected !== severity) return false;
    }
    return true;
  });

  return (
    <div className="healer-card" style={{ marginTop: 20 }}>
      <div className="healer-card-title">Logs</div>
      <p className="healer-card-description" style={{ marginBottom: 12 }}>
        Bounded recent view and live tail of one instance&apos;s stdout/stderr, or this
        application&apos;s deployment logs. Secrets and credentials are redacted before they leave
        the server.
      </p>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {sources.length === 0 && <option value="">No log sources yet</option>}
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
        {source && source.type !== "deployment" && (
          <>
            <input
              placeholder="Filter (substring)"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="">All severities</option>
              {SEVERITY_HINTS.map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
            {!live ? (
              <button onClick={startLive}>Start live tail</button>
            ) : (
              <button onClick={stopLive}>Stop live tail</button>
            )}
            <button onClick={loadOnce} disabled={live}>
              Refresh
            </button>
          </>
        )}
      </div>

      {error && (
        <div className="healer-error" style={{ marginTop: 12 }}>
          {error}
        </div>
      )}

      {source && source.type === "deployment" ? (
        <ul className="healer-issue-list" style={{ marginTop: 12 }}>
          {deployments.length === 0 && <p className="healer-card-description">No deployments yet.</p>}
          {deployments.map((d) => (
            <li key={d.id} className="healer-issue healer-issue-info">
              <span className="healer-issue-field">{d.status}</span>
              deployment {d.id}
            </li>
          ))}
        </ul>
      ) : (
        <pre
          style={{
            marginTop: 12,
            maxHeight: 360,
            overflowY: "auto",
            background: "var(--healer-input-bg)",
            color: "var(--healer-text)",
            padding: 12,
            borderRadius: 6,
            fontSize: 12,
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
          }}
        >
          {displayLines.length === 0 ? "No log lines yet." : displayLines.join("\n")}
        </pre>
      )}
      {chunk?.truncated && (
        <p className="healer-card-description" style={{ marginTop: 8 }}>
          Showing the most recent lines only — the file has more.
        </p>
      )}
    </div>
  );
}
