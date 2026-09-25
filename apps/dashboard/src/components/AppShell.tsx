"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Avatar,
  Badge,
  Box,
  Dialog,
  Flex,
  IconButton,
  ScrollArea,
  Text,
  Tooltip,
} from "@radix-ui/themes";
import { Cross1Icon, HamburgerMenuIcon } from "@radix-ui/react-icons";
import { LogoutButton } from "@/components/LogoutButton";
import { NAV_ITEMS } from "@/lib/nav";
import { hasPermission } from "@/lib/permissions";
import type { CurrentUser } from "@/lib/types";

const OVERVIEW_ITEM = { href: "/", label: "Overview", description: "At-a-glance system status." };

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavList({ user, onNavigate }: { user: CurrentUser; onNavigate?: () => void }) {
  const pathname = usePathname();
  const items = [
    OVERVIEW_ITEM,
    ...NAV_ITEMS.filter((item) => !item.permission || hasPermission(user.roles, item.permission)),
  ];

  return (
    <Flex direction="column" gap="1" aria-label="Main navigation" asChild>
      <nav>
        {items.map((item) => {
          const active = isActive(pathname ?? "", item.href);
          return (
            <Tooltip key={item.href} content={item.description} side="right" delayDuration={400}>
              <Link
                href={item.href}
                onClick={onNavigate}
                className="healer-rail-link"
                data-active={active || undefined}
                aria-current={active ? "page" : undefined}
              >
                <span className="healer-rail-dot" aria-hidden="true" />
                <Text size="2" weight={active ? "bold" : "medium"}>
                  {item.label}
                </Text>
              </Link>
            </Tooltip>
          );
        })}
      </nav>
    </Flex>
  );
}

function UserCard({ user }: { user: CurrentUser }) {
  const initial = user.email.charAt(0).toUpperCase();
  return (
    <Box className="healer-user-card">
      <Flex align="center" gap="2" mb="2">
        <Avatar size="2" radius="full" fallback={initial} color="iris" variant="solid" />
        <Box style={{ minWidth: 0, flex: 1 }}>
          <Text
            as="div"
            size="2"
            weight="medium"
            style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          >
            {user.email}
          </Text>
          <Flex gap="1" wrap="wrap" mt="1">
            {user.roles.map((role) => (
              <Badge key={role} color="iris" variant="soft" size="1">
                {role}
              </Badge>
            ))}
          </Flex>
        </Box>
      </Flex>
      <LogoutButton />
    </Box>
  );
}

/** The Healer app shell: a persistent icon-accented rail on md+ viewports,
 * collapsing to a sticky top bar with a slide-in Radix Dialog drawer below
 * that — one structure, two responsive presentations, rather than the same
 * nav simply reflowing horizontally at the old single breakpoint.
 */
export function AppShell({ user, children }: { user: CurrentUser; children: React.ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="healer-shell">
      <Box className="healer-rail" asChild>
        <aside aria-label="Sidebar">
          <Flex direction="column" style={{ height: "100%" }}>
            <Box className="healer-brand-block">
              <Text as="div" size="4" weight="bold" className="healer-brand-text">
                Healer
              </Text>
              <Text as="div" size="1" color="gray">
                V1 — deployment &amp; app management
              </Text>
            </Box>
            <ScrollArea type="auto" scrollbars="vertical" style={{ flex: 1 }}>
              <Box px="2" py="2">
                <NavList user={user} />
              </Box>
            </ScrollArea>
            <Box className="healer-rail-footer">
              <UserCard user={user} />
            </Box>
          </Flex>
        </aside>
      </Box>

      <Flex direction="column" className="healer-content-column">
        <Flex asChild align="center" justify="between" className="healer-topbar">
          <header>
            <Flex align="center" gap="2">
              <Dialog.Root open={drawerOpen} onOpenChange={setDrawerOpen}>
                <Dialog.Trigger>
                  <IconButton
                    variant="soft"
                    color="gray"
                    className="healer-hamburger"
                    aria-label="Open navigation menu"
                  >
                    <HamburgerMenuIcon width="18" height="18" />
                  </IconButton>
                </Dialog.Trigger>
                <Dialog.Content className="healer-drawer" aria-describedby={undefined}>
                  <Flex justify="between" align="center" mb="4">
                    <Dialog.Title size="4" mb="0">
                      Healer
                    </Dialog.Title>
                    <Dialog.Close>
                      <IconButton variant="soft" color="gray" aria-label="Close navigation menu">
                        <Cross1Icon />
                      </IconButton>
                    </Dialog.Close>
                  </Flex>
                  <NavList user={user} onNavigate={() => setDrawerOpen(false)} />
                  <Box mt="5">
                    <UserCard user={user} />
                  </Box>
                </Dialog.Content>
              </Dialog.Root>
              <Text size="3" weight="bold" className="healer-topbar-brand">
                Healer
              </Text>
            </Flex>
          </header>
        </Flex>

        <main id="main-content" className="healer-main">
          {children}
        </main>
      </Flex>
    </div>
  );
}
