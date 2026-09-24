import type { ReactNode } from "react";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { CurrentUserProvider } from "@/components/CurrentUserProvider";
import { Sidebar } from "@/components/Sidebar";
import { CONTROL_PLANE_INTERNAL_URL } from "@/lib/config";
import type { CurrentUser } from "@/lib/types";

async function getCurrentUser(): Promise<CurrentUser | null> {
  const cookieHeader = cookies().toString();
  const response = await fetch(`${CONTROL_PLANE_INTERNAL_URL}/auth/me`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });
  if (!response.ok) {
    return null;
  }
  return response.json();
}

// Server-side auth check for this route group — defense in depth alongside
// src/middleware.ts, which already redirects unauthenticated requests
// before they get this far. Read from here, this is the ground truth: the
// Control Plane is the only thing that knows whether a session is valid.
export default async function DashboardLayout({ children }: { children: ReactNode }) {
  const user = await getCurrentUser();
  if (!user) {
    redirect("/login");
  }

  return (
    <CurrentUserProvider user={user}>
      <a className="healer-skip-link" href="#main-content">
        Skip to main content
      </a>
      <div className="healer-shell">
        <Sidebar user={user} />
        <main id="main-content" className="healer-main">
          {children}
        </main>
      </div>
    </CurrentUserProvider>
  );
}
