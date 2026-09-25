"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ExitIcon } from "@radix-ui/react-icons";
import { CONTROL_PLANE_URL } from "@/lib/config";
import { readCsrfToken } from "@/lib/csrf";

export function LogoutButton() {
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);

  async function handleLogout() {
    setLoggingOut(true);
    const csrfToken = readCsrfToken();
    try {
      await fetch(`${CONTROL_PLANE_URL}/auth/logout`, {
        method: "POST",
        credentials: "include",
        headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
      });
    } finally {
      router.push("/login");
      router.refresh();
    }
  }

  return (
    <button className="healer-logout-button" onClick={handleLogout} disabled={loggingOut}>
      <ExitIcon width={14} height={14} />
      {loggingOut ? "Signing out…" : "Log out"}
    </button>
  );
}
