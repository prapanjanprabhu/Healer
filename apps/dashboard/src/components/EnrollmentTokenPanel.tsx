"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { CONTROL_PLANE_URL } from "@/lib/config";
import type { EnrollmentToken } from "@/lib/types";

export function EnrollmentTokenPanel({
  serverId,
  initialTokens,
}: {
  serverId: string;
  initialTokens: EnrollmentToken[];
}) {
  const router = useRouter();
  const [tokens, setTokens] = useState(initialTokens);
  const [issuedToken, setIssuedToken] = useState<string | null>(null);
  const [issuing, setIssuing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function issueToken() {
    setIssuing(true);
    setError(null);

    const response = await apiFetch(`/servers/${serverId}/enrollment-tokens`, { method: "POST" });
    setIssuing(false);

    if (!response.ok) {
      setError("Could not issue an enrollment token.");
      return;
    }

    const body = await response.json();
    setIssuedToken(body.token);
    router.refresh();

    const refreshed = await apiFetch(`/servers/${serverId}/enrollment-tokens`);
    if (refreshed.ok) {
      setTokens(await refreshed.json());
    }
  }

  async function revokeToken(tokenId: string) {
    const response = await apiFetch(`/servers/${serverId}/enrollment-tokens/${tokenId}`, {
      method: "DELETE",
    });
    if (response.ok) {
      setTokens((current) =>
        current.map((t) => (t.id === tokenId ? { ...t, revoked_at: new Date().toISOString() } : t)),
      );
    }
  }

  return (
    <div>
      <div className="healer-card" style={{ maxWidth: 640, marginBottom: 16 }}>
        <div className="healer-card-title">Enroll the Agent</div>
        <p className="healer-card-description" style={{ marginBottom: 12 }}>
          Issue a single-use enrollment token, then run this on the server (once the Agent binary
          is installed — see docs/agent-protocol.md):
        </p>
        <pre className="healer-code-block">
          {`healer-agent enroll --control-plane ${CONTROL_PLANE_URL} --token <token>`}
        </pre>

        <button onClick={issueToken} disabled={issuing}>
          {issuing ? "Issuing…" : "Issue enrollment token"}
        </button>

        {error && <div className="healer-error">{error}</div>}

        {issuedToken && (
          <div className="healer-token-reveal">
            <div>This token is shown once — copy it now:</div>
            <code>{issuedToken}</code>
          </div>
        )}
      </div>

      <div className="healer-card-title">Enrollment tokens</div>
      {tokens.length === 0 ? (
        <div className="healer-empty-state">No tokens issued yet.</div>
      ) : (
        <table className="healer-table">
          <thead>
            <tr>
              <th>Issued</th>
              <th>Expires</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {tokens.map((token) => {
              const state = token.used_at ? "used" : token.revoked_at ? "revoked" : "outstanding";
              return (
                <tr key={token.id}>
                  <td>{new Date(token.created_at).toLocaleString()}</td>
                  <td>{new Date(token.expires_at).toLocaleString()}</td>
                  <td>{state}</td>
                  <td>
                    {state === "outstanding" && (
                      <button onClick={() => revokeToken(token.id)}>Revoke</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
