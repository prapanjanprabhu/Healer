import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { EnrollmentTokenPanel } from "@/components/EnrollmentTokenPanel";
import { RevokeAgentButton } from "@/components/RevokeAgentButton";
import { CONTROL_PLANE_INTERNAL_URL } from "@/lib/config";
import type { EnrollmentToken, Server } from "@/lib/types";

async function getServer(id: string): Promise<Server | null> {
  const cookieHeader = cookies().toString();
  const response = await fetch(`${CONTROL_PLANE_INTERNAL_URL}/servers/${id}`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`failed to load server: HTTP ${response.status}`);
  }
  return response.json();
}

async function getEnrollmentTokens(id: string): Promise<EnrollmentToken[] | null> {
  const cookieHeader = cookies().toString();
  const response = await fetch(`${CONTROL_PLANE_INTERNAL_URL}/servers/${id}/enrollment-tokens`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });
  if (!response.ok) {
    return null; // e.g. 403 for a Viewer/Operator — Administrator-only
  }
  return response.json();
}

export default async function ServerDetailPage({ params }: { params: { id: string } }) {
  const server = await getServer(params.id);
  if (!server) {
    notFound();
  }
  const tokens = await getEnrollmentTokens(params.id);

  return (
    <div>
      <span
        className={server.online ? "healer-badge healer-badge-ok" : "healer-badge healer-badge-off"}
      >
        {server.online ? "Online" : "Offline"}
      </span>
      <h1 className="healer-page-title">{server.name}</h1>
      <p className="healer-page-description">
        {server.hostname} · {server.os} · registered {new Date(server.created_at).toLocaleString()}
      </p>

      <div className="healer-card" style={{ maxWidth: 480, marginBottom: 24 }}>
        <div className="healer-card-title">Connection</div>
        <dl className="healer-definition-list">
          <dt>Status</dt>
          <dd>{server.status}</dd>
          <dt>Agent version</dt>
          <dd>{server.agent_version ?? "not enrolled yet"}</dd>
          <dt>Last heartbeat</dt>
          <dd>{server.last_seen_at ? new Date(server.last_seen_at).toLocaleString() : "never"}</dd>
        </dl>
        {server.agent_version && <RevokeAgentButton serverId={server.id} />}
      </div>

      {tokens ? (
        <EnrollmentTokenPanel serverId={server.id} initialTokens={tokens} />
      ) : (
        <div className="healer-empty-state">
          Enrollment token management requires the Administrator role.
        </div>
      )}
    </div>
  );
}
