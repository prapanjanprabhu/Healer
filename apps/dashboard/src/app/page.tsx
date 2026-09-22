import Link from "next/link";
import { NAV_ITEMS } from "@/lib/nav";

export default function OverviewPage() {
  return (
    <div>
      <span className="healer-badge">Phase 1 placeholder</span>
      <h1 className="healer-page-title">Healer V1</h1>
      <p className="healer-page-description">
        One dashboard to register servers, deploy applications, and route
        traffic through the central Nginx gateway. This is the monorepo
        foundation — deployment behavior lands in a later phase.
      </p>
      <div className="healer-card-grid">
        {NAV_ITEMS.map((item) => (
          <Link key={item.href} className="healer-card" href={item.href}>
            <div className="healer-card-title">{item.label}</div>
            <div className="healer-card-description">{item.description}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}
