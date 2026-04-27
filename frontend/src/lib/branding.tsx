"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { isLocalAuthMode, getLocalAuthToken } from "@/auth/localAuth";

export interface BrandingConfig {
  productName: string;
  companyName: string;
  fullTitle: string;
  description: string;
  accentColor: string;
  accentStrong: string;
  accentSoft: string;
  /** Text colour rendered ON a solid accent background (e.g. buttons). Use dark (#111111) on bright accents. */
  accentForeground: string;
  /** Active sidebar item text/icon colour. Defaults to accentStrong. */
  accentTextOnSoft: string;
  /** Page/app background colour (--bg). */
  bg: string;
  /** Surface/panel base colour (--surface). */
  surface: string;
  /** Sidebar background colour. */
  sidebarBg: string;
  /** Card/panel background colour. */
  cardBg: string;
  logoPath: string;
  copyrightHolder: string;
}

const DEFAULTS: BrandingConfig = {
  productName: "Product Foundry",
  companyName: "AxiaCraft",
  fullTitle: "AxiaCraft Product Foundry",
  description:
    process.env.NEXT_PUBLIC_APP_DESCRIPTION ??
    "AI product engineering command centre.",
  accentColor: process.env.NEXT_PUBLIC_ACCENT_COLOR ?? "#c9972a",
  accentStrong: process.env.NEXT_PUBLIC_ACCENT_STRONG ?? "#d4a82e",
  accentSoft: process.env.NEXT_PUBLIC_ACCENT_SOFT ?? "rgba(201, 151, 42, 0.18)",
  accentForeground: process.env.NEXT_PUBLIC_ACCENT_FOREGROUND ?? "#ffffff",
  accentTextOnSoft: process.env.NEXT_PUBLIC_ACCENT_TEXT_ON_SOFT ?? (process.env.NEXT_PUBLIC_ACCENT_STRONG ?? "#d4a82e"),
  bg: process.env.NEXT_PUBLIC_BG ?? "",
  surface: process.env.NEXT_PUBLIC_SURFACE ?? "",
  sidebarBg: process.env.NEXT_PUBLIC_SIDEBAR_BG ?? "",
  cardBg: process.env.NEXT_PUBLIC_CARD_BG ?? "",
  logoPath: process.env.NEXT_PUBLIC_LOGO_PATH ?? "/axiacraft-logo.png",
  copyrightHolder: "AxiaCraft",
};

// Raw API response shape (snake_case)
interface BrandingApiResponse {
  product_name: string;
  company_name: string;
  full_title: string;
  description: string;
  accent_color: string;
  accent_strong: string;
  accent_soft: string;
  accent_foreground?: string;
  accent_text_on_soft?: string;
  bg?: string;
  surface?: string;
  sidebar_bg?: string;
  card_bg?: string;
  logo_path: string;
  copyright_holder: string;
}

function mapApiResponse(raw: BrandingApiResponse): BrandingConfig {
  return {
    productName: raw.product_name,
    companyName: raw.company_name,
    fullTitle: raw.full_title,
    description: raw.description,
    accentColor: raw.accent_color,
    accentStrong: raw.accent_strong,
    accentSoft: raw.accent_soft,
    accentForeground: raw.accent_foreground ?? DEFAULTS.accentForeground,
    accentTextOnSoft: raw.accent_text_on_soft ?? DEFAULTS.accentTextOnSoft,
    bg: raw.bg ?? DEFAULTS.bg,
    surface: raw.surface ?? DEFAULTS.surface,
    sidebarBg: raw.sidebar_bg ?? DEFAULTS.sidebarBg,
    cardBg: raw.card_bg ?? DEFAULTS.cardBg,
    logoPath: raw.logo_path,
    copyrightHolder: raw.copyright_holder,
  };
}

async function fetchDeploymentBranding(): Promise<BrandingConfig> {
  try {
    // Use the same-origin proxy route to avoid cross-origin CORS issues.
    const res = await fetch("/api/branding", { cache: "no-store" });
    if (!res.ok) return DEFAULTS;
    const data = (await res.json()) as BrandingApiResponse;
    return mapApiResponse(data);
  } catch {
    return DEFAULTS;
  }
}

/** Resolve the auth token (local-auth sessionStorage or Clerk). */
async function resolveAuthToken(): Promise<string | null> {
  if (isLocalAuthMode()) {
    return getLocalAuthToken();
  }
  // Try Clerk — dynamically import to avoid hard dep when Clerk is absent
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w = window as any;
    const clerk = w.__clerk_frontend_api ? w.__clerk : undefined;
    if (clerk?.session?.getToken) {
      return (await clerk.session.getToken()) ?? null;
    }
  } catch {
    /* ignore — Clerk not loaded yet */
  }
  return null;
}

async function fetchOrgBranding(): Promise<BrandingConfig | null> {
  try {
    const token = await resolveAuthToken();
    if (!token) return null;
    // Use the same-origin proxy route to avoid cross-origin CORS issues.
    const res = await fetch("/api/org-branding", {
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return null;
    const data = (await res.json()) as BrandingApiResponse;
    return mapApiResponse(data);
  } catch {
    return null;
  }
}

interface BrandingContextValue {
  branding: BrandingConfig;
  /** Re-fetch org branding (call after save / auth change). */
  refreshBranding: () => Promise<void>;
}

const BrandingContext = createContext<BrandingContextValue>({
  branding: DEFAULTS,
  refreshBranding: async () => {},
});

export function useBranding(): BrandingConfig {
  return useContext(BrandingContext).branding;
}

/** Force a refresh of org-level branding from the API. */
export function useBrandingRefresh(): () => Promise<void> {
  return useContext(BrandingContext).refreshBranding;
}

function applyBrandingCss(branding: BrandingConfig): void {
  const root = document.documentElement;
  root.style.setProperty("--accent", branding.accentColor);
  root.style.setProperty("--accent-strong", branding.accentStrong);
  root.style.setProperty("--accent-soft", branding.accentSoft);
  root.style.setProperty("--accent-foreground", branding.accentForeground);
  root.style.setProperty("--accent-text-on-soft", branding.accentTextOnSoft);
  if (branding.bg) root.style.setProperty("--bg", branding.bg);
  if (branding.surface) root.style.setProperty("--surface", branding.surface);
  if (branding.sidebarBg) root.style.setProperty("--sidebar-bg", branding.sidebarBg);
  if (branding.cardBg) root.style.setProperty("--card-bg", branding.cardBg);
  document.title = branding.fullTitle;
}

export function BrandingProvider({ children }: { children: ReactNode }) {
  const [branding, setBranding] = useState<BrandingConfig>(DEFAULTS);

  const loadDeploymentBranding = useCallback(async () => {
    const config = await fetchDeploymentBranding();
    setBranding(config);
    applyBrandingCss(config);
  }, []);

  const refreshBranding = useCallback(async () => {
    // Try authenticated org branding first; fall back to deployment defaults
    const orgConfig = await fetchOrgBranding();
    if (orgConfig) {
      setBranding(orgConfig);
      applyBrandingCss(orgConfig);
    } else {
      const config = await fetchDeploymentBranding();
      setBranding(config);
      applyBrandingCss(config);
    }
  }, []);

  // On mount: load deployment defaults immediately
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadDeploymentBranding();
  }, [loadDeploymentBranding]);

  // After a short delay (auth may need to settle), try org branding
  useEffect(() => {
    const timer = setTimeout(() => {
      void refreshBranding();
    }, 500);
    return () => clearTimeout(timer);
  }, [refreshBranding]);

  return (
    <BrandingContext.Provider value={{ branding, refreshBranding }}>
      {children}
    </BrandingContext.Provider>
  );
}
