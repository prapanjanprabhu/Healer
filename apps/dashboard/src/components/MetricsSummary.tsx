"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Sparkline } from "@/components/Sparkline";
import type { MetricsSnapshot, Server } from "@/lib/types";

function latestValue(rows: MetricsSnapshot[], key: keyof MetricsSnapshot): number | null {
  const last = rows[rows.length - 1];
  return last ? (last[key] as number) : null;
}

function ServerMetricsCard({ server }: { server: Server }) {
  const [rows, setRows] = useState<MetricsSnapshot[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const response = await apiFetch(`/servers/${server.id}/metrics?hours=6`);
      if (!cancelled && response.ok) setRows(await response.json());
    }
    load();
    const interval = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [server.id]);

  const cpu = rows ? rows.map((r) => r.cpu_percent) : [];
  const memory = rows ? rows.map((r) => r.memory_percent) : [];
  const disk = rows ? rows.map((r) => r.disk_percent) : [];

  return (
    <div className="healer-card" style={{ minWidth: 220 }}>
      <div className="healer-card-title">
        {server.name} <span className="healer-badge">{server.online ? "online" : "offline"}</span>
      </div>
      {rows === null ? (
        <p className="healer-card-description">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="healer-card-description">No metrics reported yet.</p>
      ) : (
        <dl className="healer-definition-list">
          <dt>CPU</dt>
          <dd>
            {latestValue(rows, "cpu_percent")}%{" "}
            <Sparkline values={cpu} color="var(--healer-info)" />
          </dd>
          <dt>RAM</dt>
          <dd>
            {latestValue(rows, "memory_percent")}%{" "}
            <Sparkline values={memory} color="var(--healer-success)" />
          </dd>
          <dt>Disk</dt>
          <dd>
            {latestValue(rows, "disk_percent")}%{" "}
            <Sparkline values={disk} color="var(--healer-warning)" />
          </dd>
        </dl>
      )}
    </div>
  );
}

/** Per-server CPU/RAM/disk summary cards with a sparkline over the last six
 * hours — the dashboard side of Phase 12's agent metrics snapshots.
 */
export function MetricsSummary() {
  const [servers, setServers] = useState<Server[] | null>(null);

  useEffect(() => {
    apiFetch("/servers").then(async (response) => {
      if (response.ok) setServers(await response.json());
    });
  }, []);

  if (servers === null) return <p className="healer-card-description">Loading servers…</p>;
  if (servers.length === 0) return <p className="healer-card-description">No servers registered yet.</p>;

  return (
    <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
      {servers.map((server) => (
        <ServerMetricsCard key={server.id} server={server} />
      ))}
    </div>
  );
}
