import { cookies } from "next/headers";
import { CONTROL_PLANE_INTERNAL_URL } from "@/lib/config";
import type { AuditLogEntry } from "@/lib/types";

async function getAuditLog(): Promise<{ entries: AuditLogEntry[] | null; forbidden: boolean }> {
  const cookieHeader = cookies().toString();
  const response = await fetch(`${CONTROL_PLANE_INTERNAL_URL}/audit-log?limit=200`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });
  if (response.status === 403) return { entries: null, forbidden: true };
  if (!response.ok) return { entries: null, forbidden: false };
  return { entries: await response.json(), forbidden: false };
}

export default async function AuditLogPage() {
  const { entries, forbidden } = await getAuditLog();

  return (
    <div>
      <h1 className="healer-page-title">Audit Log</h1>
      <p className="healer-page-description">
        Every login, deploy, scale, secret change, and administrative action — never a password,
        token, or secret value.
      </p>

      {forbidden ? (
        <p className="healer-card-description" style={{ marginTop: 20 }}>
          Viewing the audit log requires the Administrator role.
        </p>
      ) : entries === null ? (
        <div className="healer-error" style={{ marginTop: 20 }}>
          Could not reach the Control Plane — the audit log is unavailable right now.
        </div>
      ) : entries.length === 0 ? (
        <p className="healer-card-description" style={{ marginTop: 20 }}>
          No audit entries yet.
        </p>
      ) : (
        <table className="healer-table" style={{ marginTop: 20 }}>
          <thead>
            <tr>
              <th>When</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Target</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td>{new Date(e.occurred_at).toLocaleString()}</td>
                <td>{e.actor_email ?? "system"}</td>
                <td>{e.action}</td>
                <td>
                  {e.target_type}:{e.target_id}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
