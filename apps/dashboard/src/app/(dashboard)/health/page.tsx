"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { Notification } from "@/lib/types";

export default function HealthPage() {
  const [notifications, setNotifications] = useState<Notification[] | null>(null);

  async function load() {
    const response = await apiFetch("/notifications");
    if (response.ok) setNotifications(await response.json());
  }

  useEffect(() => {
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  async function markRead(id: string) {
    await apiFetch(`/notifications/${id}/read`, { method: "POST" });
    load();
  }

  return (
    <div>
      <h1 className="healer-page-title">Health</h1>
      <p className="healer-page-description">
        Self-healing alerts — instances Healer could not automatically recover. Per-instance
        health, state, and failure reason are on each application&apos;s own page.
      </p>

      <div className="healer-card" style={{ maxWidth: 720, marginTop: 20 }}>
        <div className="healer-card-title">Notifications</div>
        {!notifications || notifications.length === 0 ? (
          <p className="healer-card-description">No notifications.</p>
        ) : (
          <ul className="healer-issue-list">
            {notifications.map((n) => (
              <li
                key={n.id}
                className={`healer-issue healer-issue-${n.read_at ? "info" : "error"}`}
                style={{ display: "flex", justifyContent: "space-between", gap: 12 }}
              >
                <span>
                  <span className="healer-issue-field">{n.notification_type}</span>
                  {n.message}
                </span>
                {!n.read_at && (
                  <button onClick={() => markRead(n.id)} style={{ flexShrink: 0 }}>
                    Mark read
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
