import Link from "next/link";
import { LogoutButton } from "@/components/LogoutButton";
import { NAV_ITEMS } from "@/lib/nav";
import type { CurrentUser } from "@/lib/types";

export function Sidebar({ user }: { user: CurrentUser }) {
  return (
    <aside className="healer-sidebar">
      <div className="healer-brand">Healer</div>
      <div className="healer-brand-subtitle">V1 — deployment &amp; app management</div>
      <nav className="healer-nav">
        <Link className="healer-nav-item" href="/">
          Overview
        </Link>
        {NAV_ITEMS.map((item) => (
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
