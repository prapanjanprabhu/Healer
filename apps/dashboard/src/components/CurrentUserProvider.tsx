"use client";

import { createContext, useContext, type ReactNode } from "react";
import { hasPermission } from "@/lib/permissions";
import type { CurrentUser } from "@/lib/types";

const CurrentUserContext = createContext<CurrentUser | null>(null);

/** Makes the already-authenticated user (fetched server-side in
 * (dashboard)/layout.tsx) available to client components, so panels/buttons
 * can hide destructive or administrative actions from users who don't hold
 * the relevant permission — see src/lib/permissions.ts.
 */
export function CurrentUserProvider({ user, children }: { user: CurrentUser; children: ReactNode }) {
  return <CurrentUserContext.Provider value={user}>{children}</CurrentUserContext.Provider>;
}

export function useCurrentUser(): CurrentUser {
  const user = useContext(CurrentUserContext);
  if (!user) {
    throw new Error("useCurrentUser() called outside CurrentUserProvider");
  }
  return user;
}

export function useHasPermission(permission: string): boolean {
  const user = useCurrentUser();
  return hasPermission(user.roles, permission);
}
