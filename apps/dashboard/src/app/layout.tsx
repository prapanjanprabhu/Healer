import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { Theme } from "@radix-ui/themes";
import "@radix-ui/themes/styles.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Healer",
  description: "Self-hosted deployment and application-management platform.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark" style={{ colorScheme: "dark" }}>
      <body>
        <Theme
          appearance="dark"
          accentColor="ruby"
          grayColor="slate"
          radius="large"
          scaling="100%"
          panelBackground="translucent"
        >
          {children}
        </Theme>
      </body>
    </html>
  );
}
