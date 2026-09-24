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
  if (!response.ok) return null;
  return response.json();
}

export default async function CertificatesPage() {
  const applications = await getApplications();
  const withDomains = applications?.filter((a) => a.config.domain?.hostname) ?? [];

  return (
    <div>
      <h1 className="healer-page-title">Certificates</h1>
      <p className="healer-page-description">
        Existing CRT/KEY filesystem paths referenced by each application&apos;s domain — Healer never
        generates or uploads certificate material (no ACME). See docs/security-boundaries.md.
      </p>

      {applications === null ? (
        <div className="healer-error" style={{ marginTop: 20 }}>
          Could not reach the Control Plane — certificate references are unavailable right now.
        </div>
      ) : withDomains.length === 0 ? (
        <p className="healer-card-description" style={{ marginTop: 20 }}>
          No application has a domain configured yet.
        </p>
      ) : (
        <table className="healer-table" style={{ marginTop: 20 }}>
          <thead>
            <tr>
              <th>Application</th>
              <th>Hostname</th>
              <th>Certificate path</th>
              <th>Key path</th>
            </tr>
          </thead>
          <tbody>
            {withDomains.map((a) => (
              <tr key={a.id}>
                <td>
                  <Link href={`/applications/${a.id}`}>{a.name}</Link>
                </td>
                <td>{a.config.domain?.hostname}</td>
                <td>{a.config.domain?.cert_path ?? "—"}</td>
                <td>{a.config.domain?.key_path ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
