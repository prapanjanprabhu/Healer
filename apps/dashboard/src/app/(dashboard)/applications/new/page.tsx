"use client";

import { type FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { AdapterName, HealerYamlConfig, Server } from "@/lib/types";

const DEFAULT_WINDOWS: NonNullable<HealerYamlConfig["windows"]> = {
  python_executable: "",
  requirements_file: "requirements.txt",
  manage_py: "manage.py",
  wsgi_module: "",
  settings_module: "",
};

const DEFAULT_LINUX: NonNullable<HealerYamlConfig["linux"]> = { internal_port: 8000 };

export default function NewApplicationPage() {
  const router = useRouter();
  const [servers, setServers] = useState<Server[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [name, setName] = useState("");
  const [adapter, setAdapter] = useState<AdapterName>("windows-waitress-service");
  const [serverId, setServerId] = useState("");
  const [sourceType, setSourceType] = useState<"folder" | "git" | "dockerfile" | "image">("folder");
  const [sourceLocation, setSourceLocation] = useState("");
  const [windows, setWindows] = useState(DEFAULT_WINDOWS);
  const [linux, setLinux] = useState(DEFAULT_LINUX);
  const [healthPath, setHealthPath] = useState("/health/");
  const [portStart, setPortStart] = useState(9034);
  const [portEnd, setPortEnd] = useState(9039);
  const [minReplicas, setMinReplicas] = useState(1);
  const [maxReplicas, setMaxReplicas] = useState(1);
  const [hostname, setHostname] = useState("");
  const [certPath, setCertPath] = useState("");
  const [keyPath, setKeyPath] = useState("");
  const [secretsText, setSecretsText] = useState("");

  useEffect(() => {
    apiFetch("/servers").then(async (response) => {
      if (response.ok) setServers(await response.json());
    });
  }, []);

  function switchAdapter(next: AdapterName) {
    setAdapter(next);
    setSourceType(next === "windows-waitress-service" ? "folder" : "dockerfile");
  }

  const matchingServers = servers.filter((s) => s.os === (adapter === "windows-waitress-service" ? "windows" : "linux"));

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    const config: HealerYamlConfig = {
      version: 1,
      name,
      adapter,
      server_id: serverId || null,
      source: { type: sourceType, location: sourceLocation },
      windows: adapter === "windows-waitress-service" ? windows : null,
      linux: adapter === "linux-docker" ? linux : null,
      health: { path: healthPath, interval_seconds: 10, timeout_seconds: 5, healthy_threshold: 2, unhealthy_threshold: 3 },
      ports: { start: portStart, end: portEnd },
      replicas: { min: minReplicas, max: maxReplicas },
      domain: hostname ? { hostname, cert_path: certPath || null, key_path: keyPath || null } : null,
      secrets: secretsText
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean),
    };

    const response = await apiFetch("/applications", { method: "POST", body: JSON.stringify(config) });
    setSubmitting(false);

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "Could not save the application — check the fields below.");
      return;
    }

    const application = await response.json();
    router.push(`/applications/${application.id}`);
    router.refresh();
  }

  return (
    <div>
      <h1 className="healer-page-title">Add Application</h1>
      <p className="healer-page-description">
        Describe an application the way <code>healer.yaml</code> would — this saves and can be validated,
        but does not deploy anything yet.
      </p>

      <form className="healer-card" style={{ maxWidth: 640 }} onSubmit={handleSubmit}>
        <label className="healer-field">
          Name
          <input required value={name} onChange={(e) => setName(e.target.value)} />
        </label>

        <label className="healer-field">
          Adapter
          <select value={adapter} onChange={(e) => switchAdapter(e.target.value as AdapterName)}>
            <option value="windows-waitress-service">Windows — Django/Waitress</option>
            <option value="linux-docker">Linux — Docker</option>
          </select>
        </label>

        <label className="healer-field">
          Target server
          <select required value={serverId} onChange={(e) => setServerId(e.target.value)}>
            <option value="" disabled>
              Select a {adapter === "windows-waitress-service" ? "Windows" : "Linux"} server…
            </option>
            {matchingServers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.hostname})
              </option>
            ))}
          </select>
        </label>

        <label className="healer-field">
          Source type
          <select value={sourceType} onChange={(e) => setSourceType(e.target.value as typeof sourceType)}>
            {adapter === "windows-waitress-service" ? (
              <>
                <option value="folder">Existing folder</option>
                <option value="git">Git repository</option>
              </>
            ) : (
              <>
                <option value="dockerfile">Dockerfile</option>
                <option value="image">Pre-built image</option>
              </>
            )}
          </select>
        </label>

        <label className="healer-field">
          {sourceType === "folder" && "Folder path"}
          {sourceType === "git" && "Git URL"}
          {sourceType === "dockerfile" && "Dockerfile path"}
          {sourceType === "image" && "Image reference"}
          <input
            required
            placeholder={sourceType === "folder" ? "C:\\apps\\erp" : sourceType === "image" ? "myrepo/app:latest" : ""}
            value={sourceLocation}
            onChange={(e) => setSourceLocation(e.target.value)}
          />
        </label>

        {adapter === "windows-waitress-service" ? (
          <>
            <label className="healer-field">
              Python executable
              <input
                required
                placeholder="C:\apps\erp\venv\Scripts\python.exe"
                value={windows.python_executable}
                onChange={(e) => setWindows({ ...windows, python_executable: e.target.value })}
              />
            </label>
            <label className="healer-field">
              Requirements file (relative to source)
              <input
                value={windows.requirements_file}
                onChange={(e) => setWindows({ ...windows, requirements_file: e.target.value })}
              />
            </label>
            <label className="healer-field">
              manage.py (relative to source)
              <input value={windows.manage_py} onChange={(e) => setWindows({ ...windows, manage_py: e.target.value })} />
            </label>
            <label className="healer-field">
              WSGI module
              <input
                required
                placeholder="erp.wsgi"
                value={windows.wsgi_module}
                onChange={(e) => setWindows({ ...windows, wsgi_module: e.target.value })}
              />
            </label>
            <label className="healer-field">
              Settings module
              <input
                required
                placeholder="erp.settings.production"
                value={windows.settings_module}
                onChange={(e) => setWindows({ ...windows, settings_module: e.target.value })}
              />
            </label>
          </>
        ) : (
          <label className="healer-field">
            Internal container port
            <input
              type="number"
              required
              value={linux.internal_port}
              onChange={(e) => setLinux({ internal_port: Number(e.target.value) })}
            />
          </label>
        )}

        <label className="healer-field">
          Health check path
          <input required value={healthPath} onChange={(e) => setHealthPath(e.target.value)} />
        </label>

        <div style={{ display: "flex", gap: 12 }}>
          <label className="healer-field" style={{ flex: 1 }}>
            Port range start
            <input type="number" required value={portStart} onChange={(e) => setPortStart(Number(e.target.value))} />
          </label>
          <label className="healer-field" style={{ flex: 1 }}>
            Port range end
            <input type="number" required value={portEnd} onChange={(e) => setPortEnd(Number(e.target.value))} />
          </label>
        </div>

        <div style={{ display: "flex", gap: 12 }}>
          <label className="healer-field" style={{ flex: 1 }}>
            Minimum replicas
            <input
              type="number"
              min={1}
              required
              value={minReplicas}
              onChange={(e) => setMinReplicas(Number(e.target.value))}
            />
          </label>
          <label className="healer-field" style={{ flex: 1 }}>
            Maximum replicas
            <input
              type="number"
              min={minReplicas}
              required
              value={maxReplicas}
              onChange={(e) => setMaxReplicas(Number(e.target.value))}
            />
          </label>
        </div>

        <label className="healer-field">
          Domain hostname (optional)
          <input placeholder="erp.ritrjpm.edu.in" value={hostname} onChange={(e) => setHostname(e.target.value)} />
        </label>
        {hostname && (
          <>
            <label className="healer-field">
              Existing certificate (.crt) path
              <input value={certPath} onChange={(e) => setCertPath(e.target.value)} />
            </label>
            <label className="healer-field">
              Existing key (.key) path
              <input value={keyPath} onChange={(e) => setKeyPath(e.target.value)} />
            </label>
          </>
        )}

        <label className="healer-field">
          Secret keys needed (one per line — values are set afterward, never here)
          <textarea
            rows={3}
            value={secretsText}
            onChange={(e) => setSecretsText(e.target.value)}
            placeholder={"DB_PASSWORD\nDJANGO_SECRET_KEY"}
          />
        </label>

        {error && <div className="healer-error">{error}</div>}

        <button type="submit" disabled={submitting}>
          {submitting ? "Saving…" : "Save application"}
        </button>
      </form>
    </div>
  );
}
