import Link from "next/link";
import { cookies } from "next/headers";
import { CONTROL_PLANE_INTERNAL_URL } from "@/lib/config";
import type { Application } from "@/lib/types";

async function getApplications(): Promise<Application[] | null> {
  const cookieHeader = cookies().toString();
  const response = await fetch(`${CONTROL_PLANE_INTERNAL_URL}/applications`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });
  if (!response.ok) {
    return null;
  }
  return response.json();
}

export default async function ApplicationsPage() {
  const applications = await getApplications();

  return (
    <div>
      <h1 className="healer-page-title">Applications</h1>
      <p className="healer-page-description">
        Connect an existing application folder, Git repository, Dockerfile, or image.
      </p>

      <Link className="healer-primary-button" href="/applications/new">
        Add Application
      </Link>

      {applications === null ? (
        <div className="healer-error" style={{ marginTop: 20 }}>
          Could not reach the Control Plane — applications are unavailable right now.
        </div>
      ) : applications.length === 0 ? (
        <div className="healer-empty-state" style={{ marginTop: 20 }}>
          No applications yet.
        </div>
      ) : (
        <table className="healer-table" style={{ marginTop: 20 }}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Adapter</th>
              <th>Domain</th>
              <th>Ports</th>
            </tr>
          </thead>
          <tbody>
            {applications.map((app) => (
              <tr key={app.id}>
                <td>
                  <Link href={`/applications/${app.id}`}>{app.name}</Link>
                </td>
                <td>{app.adapter_type}</td>
                <td>{app.config.domain?.hostname ?? "—"}</td>
                <td>
                  {app.port_range_start && app.port_range_end
                    ? `${app.port_range_start}–${app.port_range_end}`
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
