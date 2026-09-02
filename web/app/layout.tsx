import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "medsafe — what your medicines are, and whether they clash",
  description:
    "Look up an Indian medicine by brand or ingredient, find cheaper equivalents, and see what is known — and what is not known — about taking it with everything else.",
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
