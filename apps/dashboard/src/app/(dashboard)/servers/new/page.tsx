"use client";

import { type FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";

export default function NewServerPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [hostname, setHostname] = useState("");
  const [os, setOs] = useState<"linux" | "windows">("linux");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    const response = await apiFetch("/servers", {
      method: "POST",
      body: JSON.stringify({ name, hostname, os }),
    });

    setSubmitting(false);

    if (!response.ok) {
      setError(response.status === 409 ? "That hostname is already registered." : "Could not register the server.");
      return;
    }

    const server = await response.json();
    router.push(`/servers/${server.id}`);
    router.refresh();
  }

  return (
    <div>
      <h1 className="healer-page-title">Add Server</h1>
      <p className="healer-page-description">
        Register a Windows or Linux server, then issue an enrollment token to install the Agent on it.
      </p>

      <form className="healer-card" style={{ maxWidth: 420 }} onSubmit={handleSubmit}>
        <label className="healer-field">
          Name
          <input required value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="healer-field">
          Hostname
          <input
            required
            placeholder="erp-01.internal"
            value={hostname}
            onChange={(e) => setHostname(e.target.value)}
          />
        </label>
        <label className="healer-field">
          Operating system
          <select value={os} onChange={(e) => setOs(e.target.value as "linux" | "windows")}>
            <option value="linux">Linux</option>
            <option value="windows">Windows</option>
          </select>
        </label>

        {error && <div className="healer-error">{error}</div>}

        <button type="submit" disabled={submitting}>
          {submitting ? "Registering…" : "Register server"}
        </button>
      </form>
    </div>
  );
}
