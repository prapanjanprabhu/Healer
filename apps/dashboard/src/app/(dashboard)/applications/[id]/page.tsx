import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { DeployPanel } from "@/components/DeployPanel";
import { GatewayPanel } from "@/components/GatewayPanel";
import { ValidatePanel } from "@/components/ValidatePanel";
import { CONTROL_PLANE_INTERNAL_URL } from "@/lib/config";
import type { Application, SecretKey } from "@/lib/types";

async function getApplication(id: string): Promise<Application | null> {
  const cookieHeader = cookies().toString();
  const response = await fetch(`${CONTROL_PLANE_INTERNAL_URL}/applications/${id}`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`failed to load application: HTTP ${response.status}`);
  return response.json();
}

async function getSecrets(id: string): Promise<SecretKey[]> {
  const cookieHeader = cookies().toString();
  const response = await fetch(`${CONTROL_PLANE_INTERNAL_URL}/applications/${id}/secrets`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });
  if (!response.ok) return [];
  return response.json();
}

export default async function ApplicationDetailPage({ params }: { params: { id: string } }) {
  const application = await getApplication(params.id);
  if (!application) notFound();
  const secrets = await getSecrets(params.id);

  const config = application.config;

  return (
    <div>
      <span className="healer-badge">{application.adapter_type}</span>
      <h1 className="healer-page-title">{application.name}</h1>
      <p className="healer-page-description">
        slug: {application.slug}
        {config.domain?.hostname ? ` · ${config.domain.hostname}` : ""}
        {application.port_range_start ? ` · ports ${application.port_range_start}-${application.port_range_end}` : ""}
      </p>

      <div className="healer-card" style={{ maxWidth: 640, marginBottom: 20 }}>
        <div className="healer-card-title">Configuration</div>
        <dl className="healer-definition-list">
          <dt>Source</dt>
          <dd>
            {config.source.type}: {config.source.location}
          </dd>
          {config.windows && (
            <>
              <dt>Python</dt>
              <dd>{config.windows.python_executable}</dd>
              <dt>WSGI module</dt>
              <dd>{config.windows.wsgi_module}</dd>
              <dt>Settings module</dt>
              <dd>{config.windows.settings_module}</dd>
            </>
          )}
          {config.linux && (
            <>
              <dt>Internal port</dt>
              <dd>{config.linux.internal_port}</dd>
            </>
          )}
          <dt>Health path</dt>
          <dd>{config.health.path}</dd>
          {config.domain?.cert_path && (
            <>
              <dt>Certificate</dt>
              <dd>{config.domain.cert_path}</dd>
            </>
          )}
        </dl>
      </div>

      <ValidatePanel applicationId={application.id} secretNames={config.secrets} initialSecrets={secrets} />
      <DeployPanel applicationId={application.id} />
      {config.domain?.hostname && (
        <GatewayPanel applicationId={application.id} hostname={config.domain.hostname} />
      )}
    </div>
  );
}
