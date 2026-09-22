import Link from "next/link";
import { NAV_ITEMS } from "@/lib/nav";

export function Sidebar() {
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
    </aside>
  );
}
