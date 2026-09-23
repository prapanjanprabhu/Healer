"use client";

import { useState } from "react";
import { apiFetch } from "@/lib/api";
import type { SecretKey, ValidationResponse } from "@/lib/types";

export function ValidatePanel({
  applicationId,
  secretNames,
  initialSecrets,
}: {
  applicationId: string;
  secretNames: string[];
  initialSecrets: SecretKey[];
}) {
  const [validating, setValidating] = useState(false);
  const [result, setResult] = useState<ValidationResponse | null>(null);
  const [secrets, setSecrets] = useState(initialSecrets);
  const [secretKey, setSecretKey] = useState(secretNames[0] ?? "");
  const [secretValue, setSecretValue] = useState("");
  const [savingSecret, setSavingSecret] = useState(false);

  async function runValidate() {
    setValidating(true);
    const response = await apiFetch(`/applications/${applicationId}/validate`, { method: "POST" });
    setValidating(false);
    if (response.ok) {
      setResult(await response.json());
    }
  }

  async function saveSecret(event: React.FormEvent) {
    event.preventDefault();
    if (!secretKey) return;
    setSavingSecret(true);
    const response = await apiFetch(`/applications/${applicationId}/secrets`, {
      method: "POST",
      body: JSON.stringify({ key: secretKey, value: secretValue }),
    });
    setSavingSecret(false);
    if (response.ok) {
      setSecretValue("");
      const listed = await apiFetch(`/applications/${applicationId}/secrets`);
      if (listed.ok) setSecrets(await listed.json());
    }
  }

  const knownKeys = new Set(secrets.map((s) => s.key));

  return (
    <div>
      <div className="healer-card" style={{ maxWidth: 640, marginBottom: 20 }}>
        <div className="healer-card-title">Validate</div>
        <p className="healer-card-description" style={{ marginBottom: 12 }}>
          Checks paths, the interpreter, Docker, port availability, the certificate pair, domain
          uniqueness, and secret references. Never deploys, migrates, or touches Nginx.
        </p>
        <button onClick={runValidate} disabled={validating}>
          {validating ? "Validating…" : "Run validation"}
        </button>

        {result && (
          <ul className="healer-issue-list" style={{ marginTop: 16 }}>
            {result.issues.length === 0 ? (
              <li className="healer-issue healer-issue-info">No issues found.</li>
            ) : (
              result.issues.map((issue, index) => (
                <li key={index} className={`healer-issue healer-issue-${issue.severity}`}>
                  <span className="healer-issue-field">{issue.field}</span>
                  {issue.message}
                </li>
              ))
            )}
          </ul>
        )}
      </div>

      {secretNames.length > 0 && (
        <div className="healer-card" style={{ maxWidth: 640 }}>
          <div className="healer-card-title">Secrets</div>
          <p className="healer-card-description" style={{ marginBottom: 12 }}>
            {secretNames.map((name) => (
              <span key={name} style={{ marginRight: 8 }}>
                {name}: {knownKeys.has(name) ? "set" : "not set"}
              </span>
            ))}
          </p>

          <form onSubmit={saveSecret}>
            <label className="healer-field">
              Key
              <select value={secretKey} onChange={(e) => setSecretKey(e.target.value)}>
                {secretNames.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label className="healer-field">
              Value
              <input
                type="password"
                value={secretValue}
                onChange={(e) => setSecretValue(e.target.value)}
                autoComplete="off"
              />
            </label>
            <button type="submit" disabled={savingSecret || !secretValue}>
              {savingSecret ? "Saving…" : "Set secret"}
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
