import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "medsafe — substitute and interaction console",
  description:
    "Find generic equivalents for a prescribed medicine and check a prescription for known drug interactions. Decision support only.",
};

export const viewport: Viewport = {
  themeColor: "#12212E",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
