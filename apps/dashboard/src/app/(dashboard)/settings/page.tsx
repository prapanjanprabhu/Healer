"use client";

import { type FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { useCurrentUser } from "@/components/CurrentUserProvider";

export default function SettingsPage() {
  const user = useCurrentUser();
  const router = useRouter();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const response = await apiFetch("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
    setSubmitting(false);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "Could not change your password.");
      return;
    }
    router.push("/login?next=%2Fsettings");
    router.refresh();
  }

  return (
    <div>
      <h1 className="healer-page-title">Settings</h1>
      <p className="healer-page-description">Your account and this deployment&apos;s operational defaults.</p>

      <div className="healer-card" style={{ maxWidth: 480, marginTop: 20 }}>
        <div className="healer-card-title">Account</div>
        <dl className="healer-definition-list">
          <dt>Email</dt>
          <dd>{user.email}</dd>
          <dt>Roles</dt>
          <dd>{user.roles.join(", ")}</dd>
        </dl>
      </div>

      <div className="healer-card" style={{ maxWidth: 480, marginTop: 20 }}>
        <div className="healer-card-title">Change password</div>
        <form onSubmit={handleSubmit}>
          <label className="healer-field">
            Current password
            <input
              required
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
            />
          </label>
          <label className="healer-field">
            New password
            <input
              required
              type="password"
              minLength={8}
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </label>
          {error && <div className="healer-error">{error}</div>}
          <button type="submit" disabled={submitting}>
            {submitting ? "Changing…" : "Change password"}
          </button>
        </form>
        <p className="healer-card-description" style={{ marginTop: 8 }}>
          Changing your password signs you out everywhere else and requires logging in again here.
        </p>
      </div>

      <div className="healer-card" style={{ maxWidth: 480, marginTop: 20 }}>
        <div className="healer-card-title">Operational defaults</div>
        <p className="healer-card-description">
          These are set for the whole deployment via environment configuration, not per-user —
          see docs/metrics-and-logs.md and docs/self-healing.md.
        </p>
        <dl className="healer-definition-list">
          <dt>Metrics retention</dt>
          <dd>7 days (default)</dd>
          <dt>Health check loop</dt>
          <dd>Continuous, every 5 seconds per due instance</dd>
        </dl>
      </div>
    </div>
  );
}
