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
  // Optional, not just in the type sense: the Control Plane falls back to
  // `{}` for a row whose stored config is missing/corrupted (see
  // ApplicationOut.from_model, `config=application.config or {}`), so a
  // real API response can omit every field below this line.
  source?: { type: "folder" | "git" | "dockerfile" | "image"; location: string; ref?: string | null };
  windows?: {
    python_executable: string;
    requirements_file: string;
    manage_py: string;
    wsgi_module: string;
    settings_module: string;
  } | null;
  linux?: {
    internal_port: number;
    env?: Record<string, string>;
    cpu_limit?: number | null;
    memory_limit_mb?: number | null;
  } | null;
  health?: {
    path: string;
    interval_seconds: number;
    timeout_seconds: number;
    healthy_threshold: number;
    unhealthy_threshold: number;
  };
  ports?: { start: number; end: number };
  replicas?: { min: number; max: number };
  domain?: { hostname: string; cert_path?: string | null; key_path?: string | null } | null;
  secrets?: string[];
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
  min_replicas: number;
  max_replicas: number;
  desired_replicas: number;
  active_release_id: string | null;
  release_retention_count: number;
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
  kind: string;
  failure_reason: string | null;
  instances: DeploymentInstance[];
  steps: DeploymentStep[];
  logs: DeploymentLogEntry[];
  created_at: string;
  updated_at: string;
}

export interface GatewaySyncResponse {
  ok: boolean;
  message: string;
}

export interface ScaleTriggerResponse {
  deployment_id: string;
  desired_replicas: number;
}

export interface Notification {
  id: string;
  notification_type: string;
  message: string;
  read_at: string | null;
  created_at: string;
}

export interface ReleaseTriggerResponse {
  deployment_id: string;
  warnings: string[];
}

export interface Release {
  id: string;
  ref: string;
  status: string;
  is_active: boolean;
  created_at: string;
}

export interface MetricsSnapshot {
  server_id: string;
  cpu_percent: number;
  memory_percent: number;
  disk_percent: number;
  recorded_at: string;
}

export interface LogSource {
  id: string;
  type: "stdout" | "stderr" | "deployment";
  label: string;
  instance_id: string | null;
}

export interface LogChunk {
  lines: string[];
  size: number;
  end_offset: number;
  truncated: boolean;
  not_found: boolean;
}

export interface DeploymentSummary {
  id: string;
  application_id: string;
  application_name: string;
  release_version: string | null;
  status: string;
  kind: string;
  created_at: string;
  updated_at: string;
}

export interface UserSummary {
  id: string;
  email: string;
  roles: string[];
  is_active: boolean;
  created_at: string;
}

export interface AuditLogEntry {
  id: string;
  actor_id: string | null;
  actor_email: string | null;
  action: string;
  target_type: string;
  target_id: string;
  detail: Record<string, unknown> | null;
  occurred_at: string;
}

export interface DBColumnInfo {
  name: string;
  type: string;
  nullable: boolean;
  primary_key: boolean;
  sensitive: boolean;
}

export interface DBEditableColumn {
  name: string;
  kind: "text" | "optional_text" | "select" | "boolean" | "json";
  multiline: boolean;
  choices: string[] | null;
}

export interface DBTableInfo {
  name: string;
  row_count: number;
  editable: boolean;
  deletable: boolean;
  single_column_pk: string | null;
  columns: DBColumnInfo[];
  editable_columns: DBEditableColumn[];
}

export interface DBRowsResponse {
  rows: Record<string, unknown>[];
  total: number;
  limit: number;
  offset: number;
}

export interface Instance {
  id: string;
  port: number;
  server_id: string;
  server_name: string;
  status: string;
  release_version: string;
  service_name: string | null;
  healthy: boolean | null;
  response_time_ms: number | null;
  last_checked_at: string | null;
  failure_reason: string | null;
  healing_attempts: number;
  created_at: string;
}
