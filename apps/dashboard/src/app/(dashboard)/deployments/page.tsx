import Link from "next/link";
import { cookies } from "next/headers";
import { CONTROL_PLANE_INTERNAL_URL } from "@/lib/config";
import type { DeploymentSummary } from "@/lib/types";

async function getDeployments(): Promise<DeploymentSummary[] | null> {
  const cookieHeader = cookies().toString();
  const response = await fetch(`${CONTROL_PLANE_INTERNAL_URL}/deployments`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });
  if (!response.ok) return null;
  return response.json();
}

const STATUS_CLASS: Record<string, string> = {
  failed: "healer-issue-error",
  in_progress: "healer-issue-warning",
};

export default async function DeploymentsPage() {
  const deployments = await getDeployments();

  return (
    <div>
      <h1 className="healer-page-title">Deployments</h1>
      <p className="healer-page-description">
        Every deploy, scale, blue-green release switch, and rollback across all applications.
      </p>

      {deployments === null ? (
        <div className="healer-error" style={{ marginTop: 20 }}>
          Could not reach the Control Plane — deployment history is unavailable right now.
        </div>
      ) : deployments.length === 0 ? (
        <p className="healer-card-description" style={{ marginTop: 20 }}>
          No deployments yet — deploy an application to see its history here.
        </p>
      ) : (
        <table className="healer-table" style={{ marginTop: 20 }}>
          <thead>
            <tr>
              <th>Application</th>
              <th>Kind</th>
              <th>Release</th>
              <th>Status</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {deployments.map((d) => (
              <tr key={d.id}>
                <td>{d.application_name}</td>
                <td>{d.kind}</td>
                <td>{d.release_version ?? "—"}</td>
                <td>
                  <span className={`healer-issue ${STATUS_CLASS[d.status] ?? "healer-issue-info"}`}>
                    {d.status}
                  </span>
                </td>
                <td>{new Date(d.created_at).toLocaleString()}</td>
                <td>
                  <Link href={`/deployments/${d.id}`}>View</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
