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
