import Link from "next/link";
import { cookies } from "next/headers";
import { CONTROL_PLANE_INTERNAL_URL } from "@/lib/config";
import type { Server } from "@/lib/types";

async function getServers(): Promise<Server[]> {
  const cookieHeader = cookies().toString();
  const response = await fetch(`${CONTROL_PLANE_INTERNAL_URL}/servers`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });
  if (!response.ok) {
    return [];
  }
  return response.json();
}

export default async function ServersPage() {
  const servers = await getServers();

  return (
    <div>
      <h1 className="healer-page-title">Servers</h1>
      <p className="healer-page-description">
        Register Windows and Linux servers for Healer to manage.
      </p>

      <Link className="healer-primary-button" href="/servers/new">
        Add Server
      </Link>

      {servers.length === 0 ? (
        <div className="healer-empty-state" style={{ marginTop: 20 }}>
          No servers registered yet.
        </div>
      ) : (
        <table className="healer-table" style={{ marginTop: 20 }}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Hostname</th>
              <th>OS</th>
              <th>Connection</th>
              <th>Agent version</th>
            </tr>
          </thead>
          <tbody>
            {servers.map((server) => (
              <tr key={server.id}>
                <td>
                  <Link href={`/servers/${server.id}`}>{server.name}</Link>
                </td>
                <td>{server.hostname}</td>
                <td>{server.os}</td>
                <td>
                  <span
                    className={
                      server.online ? "healer-badge healer-badge-ok" : "healer-badge healer-badge-off"
                    }
                  >
                    {server.online ? "Online" : "Offline"}
                  </span>
                </td>
                <td>{server.agent_version ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
