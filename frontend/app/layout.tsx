import "./globals.css";
import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import localFont from "next/font/local";

// Inter — the same typeface as the GalaxiaOS logo. Bundled locally (next/font/local)
// so production builds need no network, and exposed as a CSS variable that
// globals.css applies to the whole app.
const inter = localFont({
  src: "./fonts/Inter.ttf",
  variable: "--font-inter",
  weight: "100 900",
  display: "swap",
});

export const metadata: Metadata = {
  title: "GalaxiaOS — Autonomous Business Operating System",
  description: "What's your mission? What's your budget? Launch.",
  icons: { icon: "/galaxiaos-logo.png", apple: "/galaxiaos-logo.png" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Match the logo's indigo so the mobile browser chrome matches the brand.
  themeColor: "#4f46e5",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body>{children}</body>
    </html>
  );
}
