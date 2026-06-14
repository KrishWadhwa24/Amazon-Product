import type { Metadata } from "next";
import "./globals.css";
import { NavBar } from "@/components/NavBar";
import { NotificationPoller } from "@/components/NotificationPoller";
import { AuthSessionProvider } from "@/context/AuthSessionContext";

export const metadata: Metadata = {
  title: "Amazon Edge-Return",
  description:
    "Decentralized logistics, real-time return intercept, and peer-to-peer resale.",
};

/**
 * Shared root layout applying the customer-facing Amazon tokens (Req 17.1).
 *
 * The page background is amazonBg (#EAEDED) and body text uses amazonInk
 * (#0F1111) for >= 4.5:1 contrast (Req 17.4). The NavBar renders the navy top
 * bar and the secondary dark band.
 */
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-amazonBg text-amazonInk antialiased">
        <AuthSessionProvider>
          <NavBar />
          <main className="mx-auto w-full max-w-7xl px-4 py-6">{children}</main>
          {/* Global 3s match-notification poller + popup (Req 1.8, 8.1-8.5). */}
          <NotificationPoller />
        </AuthSessionProvider>
      </body>
    </html>
  );
}
