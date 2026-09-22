import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Sidebar } from "@/components/Sidebar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Healer",
  description: "Self-hosted deployment and application-management platform.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="healer-shell">
          <Sidebar />
          <main className="healer-main">{children}</main>
        </div>
      </body>
    </html>
  );
}
