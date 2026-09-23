export interface CurrentUser {
  id: string;
  email: string;
  roles: string[];
}

export interface Server {
  id: string;
  name: string;
  hostname: string;
  os: "windows" | "linux";
  status: string;
  online: boolean;
  agent_version: string | null;
  last_seen_at: string | null;
  created_at: string;
}

export interface EnrollmentToken {
  id: string;
  expires_at: string;
  used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export type AdapterName = "windows-waitress-service" | "linux-docker";

export interface HealerYamlConfig {
  version: 1;
  name: string;
  adapter: AdapterName;
  server_id: string | null;
  source: { type: "folder" | "git" | "dockerfile" | "image"; location: string; ref?: string | null };
  windows?: {
    python_executable: string;
    requirements_file: string;
    manage_py: string;
    wsgi_module: string;
    settings_module: string;
  } | null;
  linux?: { internal_port: number } | null;
  health: {
    path: string;
    interval_seconds: number;
    timeout_seconds: number;
    healthy_threshold: number;
    unhealthy_threshold: number;
  };
  ports: { start: number; end: number };
  domain?: { hostname: string; cert_path?: string | null; key_path?: string | null } | null;
  secrets: string[];
}

export interface Application {
  id: string;
  name: string;
  slug: string;
  adapter_type: AdapterName;
  server_id: string | null;
  config: HealerYamlConfig;
  port_range_start: number | null;
  port_range_end: number | null;
  created_at: string;
  updated_at: string;
}

export interface ValidationIssue {
  field: string;
  severity: "error" | "warning" | "info";
  message: string;
}

export interface ValidationResponse {
  ok: boolean;
  issues: ValidationIssue[];
}

export interface SecretKey {
  key: string;
  created_at: string;
  updated_at: string;
}

export interface DeployTriggerResponse {
  deployment_id: string;
  release_id: string;
  instance_id: string;
  port: number;
  service_name: string;
}

export interface DeploymentStep {
  name: string;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped";
  started_at: string | null;
  finished_at: string | null;
}

export interface DeploymentLogEntry {
  step_id: string | null;
  level: string;
  message: string;
  created_at: string;
}

export interface DeploymentInstance {
  id: string;
  server_id: string;
  port: number;
  service_name: string | null;
  status: string;
}

export interface DeploymentDetail {
  id: string;
  application_id: string;
  release_id: string;
  release_version: string;
  status: "pending" | "in_progress" | "succeeded" | "failed" | "rolled_back";
  instance: DeploymentInstance | null;
  steps: DeploymentStep[];
  logs: DeploymentLogEntry[];
  created_at: string;
  updated_at: string;
}
