export interface NavItem {
  href: string;
  label: string;
  description: string;
}

// Mirrors the administrator-facing capabilities from the Healer V1 product
// definition. Each route is a placeholder in Phase 1 — no data is wired up
// yet, these establish the navigation shell the real views land in later.
export const NAV_ITEMS: NavItem[] = [
  {
    href: "/servers",
    label: "Servers",
    description: "Register and manage Windows and Linux application servers.",
  },
  {
    href: "/applications",
    label: "Applications",
    description: "Connect an application folder or Git repository.",
  },
  {
    href: "/deployments",
    label: "Deployments",
    description: "Deploy releases, choose instance counts, roll back.",
  },
  {
    href: "/health",
    label: "Health",
    description: "Instance health, CPU/RAM/disk, and live/recent logs.",
  },
  {
    href: "/certificates",
    label: "Certificates",
    description: "Reference existing HTTPS certificate and key paths.",
  },
  {
    href: "/audit-log",
    label: "Audit Log",
    description: "History of administrative actions.",
  },
];
