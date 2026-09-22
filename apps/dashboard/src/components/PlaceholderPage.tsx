import type { ReactNode } from "react";

export function PlaceholderPage({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <div>
      <span className="healer-badge">Phase 1 placeholder</span>
      <h1 className="healer-page-title">{title}</h1>
      <p className="healer-page-description">{description}</p>
      {children ?? (
        <div className="healer-empty-state">
          No data yet — this view is wired up once deployment behavior is
          implemented.
        </div>
      )}
    </div>
  );
}
