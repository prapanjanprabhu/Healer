"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useCurrentUser } from "@/components/CurrentUserProvider";
import type { UserSummary } from "@/lib/types";

const ALL_ROLES = ["Administrator", "Operator", "Viewer"];

export default function UsersPage() {
  const currentUser = useCurrentUser();
  const [users, setUsers] = useState<UserSummary[] | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [roles, setRoles] = useState<string[]>(["Viewer"]);
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    const response = await apiFetch("/users");
    if (response.status === 403) {
      setForbidden(true);
      return;
    }
    if (response.ok) setUsers(await response.json());
  }

  useEffect(() => {
    load();
  }, []);

  function toggleRole(role: string) {
    setRoles((prev) => (prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role]));
  }

  async function createUser(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const response = await apiFetch("/users", {
      method: "POST",
      body: JSON.stringify({ email, password, roles }),
    });
    setSubmitting(false);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "Could not create the user.");
      return;
    }
    setEmail("");
    setPassword("");
    setRoles(["Viewer"]);
    load();
  }

  async function setUserRoles(userId: string, newRoles: string[]) {
    if (newRoles.length === 0) return;
    await apiFetch(`/users/${userId}/roles`, { method: "PATCH", body: JSON.stringify({ roles: newRoles }) });
    load();
  }

  async function toggleActive(user: UserSummary) {
    const action = user.is_active ? "deactivate" : "activate";
    if (user.is_active && !confirm(`Deactivate ${user.email}? They will no longer be able to log in.`)) {
      return;
    }
    await apiFetch(`/users/${user.id}/${action}`, { method: "POST" });
    load();
  }

  if (forbidden) {
    return (
      <div>
        <h1 className="healer-page-title">Users</h1>
        <p className="healer-card-description">Managing users requires the Administrator role.</p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="healer-page-title">Users</h1>
      <p className="healer-page-description">
        Administrator accounts and their roles. Roles are fixed in V1: Administrator (full access),
        Operator (deploy/scale/restart/stop/rollback), Viewer (read-only).
      </p>

      <div className="healer-card" style={{ maxWidth: 480, marginTop: 20 }}>
        <div className="healer-card-title">Add user</div>
        <form onSubmit={createUser}>
          <label className="healer-field">
            Email
            <input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="healer-field">
            Password
            <input
              required
              type="password"
              minLength={8}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <fieldset style={{ border: "none", padding: 0, margin: "8px 0" }}>
            <legend className="healer-field-label">Roles</legend>
            {ALL_ROLES.map((role) => (
              <label key={role} style={{ display: "inline-flex", alignItems: "center", gap: 4, marginRight: 12 }}>
                <input type="checkbox" checked={roles.includes(role)} onChange={() => toggleRole(role)} />
                {role}
              </label>
            ))}
          </fieldset>
          {error && <div className="healer-error">{error}</div>}
          <button type="submit" disabled={submitting || roles.length === 0}>
            {submitting ? "Creating…" : "Create user"}
          </button>
        </form>
      </div>

      <div style={{ marginTop: 20 }}>
        {users === null ? (
          <p className="healer-card-description">Loading…</p>
        ) : (
          <table className="healer-table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Roles</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.email}</td>
                  <td>
                    {ALL_ROLES.map((role) => (
                      <label key={role} style={{ display: "inline-flex", alignItems: "center", gap: 4, marginRight: 10 }}>
                        <input
                          type="checkbox"
                          checked={u.roles.includes(role)}
                          disabled={u.id === currentUser.id && role === "Administrator"}
                          onChange={() =>
                            setUserRoles(
                              u.id,
                              u.roles.includes(role) ? u.roles.filter((r) => r !== role) : [...u.roles, role]
                            )
                          }
                        />
                        {role}
                      </label>
                    ))}
                  </td>
                  <td>{u.is_active ? "active" : "deactivated"}</td>
                  <td>
                    <button onClick={() => toggleActive(u)} disabled={u.id === currentUser.id}>
                      {u.is_active ? "Deactivate" : "Activate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
