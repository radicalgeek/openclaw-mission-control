import "./globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { DM_Serif_Display, Inter, Sora } from "next/font/google";

import { AuthGate } from "@/components/providers/AuthGate";
import { QueryProvider } from "@/components/providers/QueryProvider";
import { GlobalLoader } from "@/components/ui/global-loader";
import { BrandingProvider } from "@/lib/branding";

export const metadata: Metadata = {
  title: process.env.NEXT_PUBLIC_APP_TITLE ?? "AxiaCraft Product Foundry",
  description:
    process.env.NEXT_PUBLIC_APP_DESCRIPTION ??
    "AI product engineering command centre.",
  icons: {
    icon: "/favicon.svg",
  },
};

const bodyFont = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-body",
  weight: ["400", "500", "600", "700"],
});

const headingFont = Sora({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-heading",
  weight: ["500", "600", "700"],
});

const displayFont = DM_Serif_Display({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-display",
  weight: ["400"],
});

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body
        className={`${bodyFont.variable} ${headingFont.variable} ${displayFont.variable} min-h-screen bg-app text-strong antialiased`}
      >
        <BrandingProvider>
          <AuthGate>
            <QueryProvider>
              <GlobalLoader />
              {children}
            </QueryProvider>
          </AuthGate>
        </BrandingProvider>
      </body>
    </html>
  );
}
