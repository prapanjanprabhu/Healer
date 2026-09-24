import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { DeploymentDetailView } from "@/components/DeploymentDetailView";
import { CONTROL_PLANE_INTERNAL_URL } from "@/lib/config";
import type { DeploymentDetail } from "@/lib/types";

async function getDeployment(id: string): Promise<DeploymentDetail | null> {
  const cookieHeader = cookies().toString();
  const response = await fetch(`${CONTROL_PLANE_INTERNAL_URL}/deployments/${id}`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`failed to load deployment: HTTP ${response.status}`);
  return response.json();
}

export default async function DeploymentDetailPage({ params }: { params: { id: string } }) {
  const detail = await getDeployment(params.id);
  if (!detail) notFound();

  return (
    <div>
      <h1 className="healer-page-title">Deployment</h1>
      <p className="healer-page-description">
        {detail.kind} for application <code>{detail.application_id}</code>, release {detail.release_version}.
      </p>
      <div className="healer-card" style={{ maxWidth: 720, marginTop: 20 }}>
        <DeploymentDetailView initialDetail={detail} />
      </div>
    </div>
  );
}
