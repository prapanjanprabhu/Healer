import Link from "next/link";
import { LogoutButton } from "@/components/LogoutButton";
import { NAV_ITEMS } from "@/lib/nav";
import { hasPermission } from "@/lib/permissions";
import type { CurrentUser } from "@/lib/types";

export function Sidebar({ user }: { user: CurrentUser }) {
  const visibleItems = NAV_ITEMS.filter(
    (item) => !item.permission || hasPermission(user.roles, item.permission)
  );
  return (
    <aside className="healer-sidebar">
      <div className="healer-brand">Healer</div>
      <div className="healer-brand-subtitle">V1 — deployment &amp; app management</div>
      <nav className="healer-nav" aria-label="Main">
        <Link className="healer-nav-item" href="/">
          Overview
        </Link>
        {visibleItems.map((item) => (
          <Link key={item.href} className="healer-nav-item" href={item.href}>
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="healer-sidebar-user">
        <div className="healer-sidebar-user-email">{user.email}</div>
        <div className="healer-sidebar-user-roles">{user.roles.join(", ")}</div>
        <LogoutButton />
      </div>
    </aside>
  );
}
