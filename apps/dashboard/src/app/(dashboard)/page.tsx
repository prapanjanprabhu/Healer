import { cookies } from "next/headers";
import { CONTROL_PLANE_INTERNAL_URL } from "@/lib/config";
import type { Application, DeploymentSummary, Notification, Server } from "@/lib/types";

async function getJson<T>(path: string): Promise<T | null> {
  const cookieHeader = cookies().toString();
  const response = await fetch(`${CONTROL_PLANE_INTERNAL_URL}${path}`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });
  if (!response.ok) return null;
  return response.json();
}

function Card({ label, value, tone }: { label: string; value: string | number; tone?: "warning" | "error" }) {
  return (
    <div className="healer-card" style={{ minWidth: 160, flex: "1 1 160px" }}>
      <div className="healer-card-title">{label}</div>
      <div
        style={{
          fontSize: 32,
          fontWeight: 600,
          color: tone === "error" ? "var(--healer-error, #d33)" : tone === "warning" ? "var(--healer-warning, #b58a00)" : undefined,
        }}
      >
        {value}
      </div>
    </div>
  );
}

export default async function OverviewPage() {
  const [servers, applications, deployments, notifications] = await Promise.all([
    getJson<Server[]>("/servers"),
    getJson<Application[]>("/applications"),
    getJson<DeploymentSummary[]>("/deployments"),
    getJson<Notification[]>("/notifications"),
  ]);

  const offline = servers === null || applications === null || deployments === null;

  const onlineServers = servers?.filter((s) => s.online).length ?? 0;
  const inProgressDeployments = deployments?.filter((d) => d.status === "in_progress").length ?? 0;
  const failedDeployments =
    deployments?.filter((d) => d.status === "failed" && isRecent(d.updated_at)).length ?? 0;
  const unreadNotifications = notifications?.filter((n) => !n.read_at).length ?? 0;

  return (
    <div>
      <h1 className="healer-page-title">Overview</h1>
      <p className="healer-page-description">A summary of everything Healer currently manages.</p>

      {offline && (
        <div className="healer-error" style={{ marginTop: 12 }}>
          Could not reach the Control Plane — the numbers below may be incomplete.
        </div>
      )}

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 20 }}>
        <Card label="Servers online" value={servers ? `${onlineServers} / ${servers.length}` : "—"} />
        <Card label="Applications" value={applications?.length ?? "—"} />
        <Card
          label="Deployments in progress"
          value={inProgressDeployments}
          tone={inProgressDeployments > 0 ? "warning" : undefined}
        />
        <Card
          label="Recent failed deployments"
          value={failedDeployments}
          tone={failedDeployments > 0 ? "error" : undefined}
        />
        <Card
          label="Unread notifications"
          value={unreadNotifications}
          tone={unreadNotifications > 0 ? "warning" : undefined}
        />
      </div>

      <div className="healer-card" style={{ marginTop: 20 }}>
        <div className="healer-card-title">Recent deployments</div>
        {!deployments || deployments.length === 0 ? (
          <p className="healer-card-description">No deployments yet.</p>
        ) : (
          <ul className="healer-issue-list">
            {deployments.slice(0, 8).map((d) => (
              <li key={d.id} className={`healer-issue healer-issue-${d.status === "failed" ? "error" : "info"}`}>
                <span className="healer-issue-field">{d.application_name}</span>
                {d.kind} — {d.status}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function isRecent(iso: string): boolean {
  return Date.now() - new Date(iso).getTime() < 24 * 3600 * 1000;
}
