export interface NavItem {
  href: string;
  label: string;
  description: string;
  // Omitted means every authenticated user sees this item. Mirrors
  // src/lib/permissions.ts's permission names.
  permission?: string;
}

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
    permission: "view_audit",
  },
  {
    href: "/users",
    label: "Users",
    description: "Manage administrator accounts and roles.",
    permission: "manage_users",
  },
  {
    href: "/db",
    label: "Database",
    description: "Browse every table; edit or delete rows on operational tables.",
    permission: "manage_db",
  },
  {
    href: "/settings",
    label: "Settings",
    description: "Your account and operational settings.",
  },
];
