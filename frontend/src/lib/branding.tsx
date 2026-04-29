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
  /** Form input bg / pressed-state surface (--surface-muted). */
  surfaceMuted: string;
  /** Hover-state / strongly elevated surface (--surface-strong). */
  surfaceStrong: string;
  /** Subtle border colour (--border). */
  border: string;
  /** Stronger border colour for emphasised edges (--border-strong). */
  borderStrong: string;
  logoPath: string;
  copyrightHolder: string;
  // Semantic colour tokens — see backend/app/core/branding.py for usage notes.
  // Each token has bg (rgba subtle), fg (saturated text), border (rgba mid).
  successBg: string;
  successFg: string;
  successBorder: string;
  warningBg: string;
  warningFg: string;
  warningBorder: string;
  dangerBg: string;
  dangerFg: string;
  dangerBorder: string;
  infoBg: string;
  infoFg: string;
  infoBorder: string;
  neutralBg: string;
  neutralFg: string;
  neutralBorder: string;
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
  surfaceMuted: process.env.NEXT_PUBLIC_SURFACE_MUTED ?? "",
  surfaceStrong: process.env.NEXT_PUBLIC_SURFACE_STRONG ?? "",
  border: process.env.NEXT_PUBLIC_BORDER ?? "",
  borderStrong: process.env.NEXT_PUBLIC_BORDER_STRONG ?? "",
  logoPath: process.env.NEXT_PUBLIC_LOGO_PATH ?? "/axiacraft-logo.png",
  copyrightHolder: "AxiaCraft",
  // Semantic token defaults — must mirror backend/app/core/branding.py _DEFAULTS.
  successBg: "rgba(34, 197, 94, 0.15)",
  successFg: "#4ade80",
  successBorder: "rgba(34, 197, 94, 0.35)",
  warningBg: "rgba(245, 158, 11, 0.15)",
  warningFg: "#fbbf24",
  warningBorder: "rgba(245, 158, 11, 0.35)",
  dangerBg: "rgba(244, 63, 94, 0.15)",
  dangerFg: "#fb7185",
  dangerBorder: "rgba(244, 63, 94, 0.35)",
  infoBg: "rgba(96, 165, 250, 0.15)",
  infoFg: "#93c5fd",
  infoBorder: "rgba(96, 165, 250, 0.35)",
  neutralBg: "rgba(148, 163, 184, 0.15)",
  neutralFg: "#cbd5e1",
  neutralBorder: "rgba(148, 163, 184, 0.35)",
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
  surface_muted?: string;
  surface_strong?: string;
  border?: string;
  border_strong?: string;
  logo_path: string;
  copyright_holder: string;
  // Semantic tokens. Optional in the response (older deployments may not
  // include them); fall back to DEFAULTS if absent.
  success_bg?: string;
  success_fg?: string;
  success_border?: string;
  warning_bg?: string;
  warning_fg?: string;
  warning_border?: string;
  danger_bg?: string;
  danger_fg?: string;
  danger_border?: string;
  info_bg?: string;
  info_fg?: string;
  info_border?: string;
  neutral_bg?: string;
  neutral_fg?: string;
  neutral_border?: string;
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
    surfaceMuted: raw.surface_muted ?? DEFAULTS.surfaceMuted,
    surfaceStrong: raw.surface_strong ?? DEFAULTS.surfaceStrong,
    border: raw.border ?? DEFAULTS.border,
    borderStrong: raw.border_strong ?? DEFAULTS.borderStrong,
    logoPath: raw.logo_path,
    copyrightHolder: raw.copyright_holder,
    successBg: raw.success_bg ?? DEFAULTS.successBg,
    successFg: raw.success_fg ?? DEFAULTS.successFg,
    successBorder: raw.success_border ?? DEFAULTS.successBorder,
    warningBg: raw.warning_bg ?? DEFAULTS.warningBg,
    warningFg: raw.warning_fg ?? DEFAULTS.warningFg,
    warningBorder: raw.warning_border ?? DEFAULTS.warningBorder,
    dangerBg: raw.danger_bg ?? DEFAULTS.dangerBg,
    dangerFg: raw.danger_fg ?? DEFAULTS.dangerFg,
    dangerBorder: raw.danger_border ?? DEFAULTS.dangerBorder,
    infoBg: raw.info_bg ?? DEFAULTS.infoBg,
    infoFg: raw.info_fg ?? DEFAULTS.infoFg,
    infoBorder: raw.info_border ?? DEFAULTS.infoBorder,
    neutralBg: raw.neutral_bg ?? DEFAULTS.neutralBg,
    neutralFg: raw.neutral_fg ?? DEFAULTS.neutralFg,
    neutralBorder: raw.neutral_border ?? DEFAULTS.neutralBorder,
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
  // Surface variants — drive form inputs (--surface-muted via globals.css
  // input rule), pressed/hover states, and any *-strong elevation.
  if (branding.surfaceMuted) root.style.setProperty("--surface-muted", branding.surfaceMuted);
  if (branding.surfaceStrong) root.style.setProperty("--surface-strong", branding.surfaceStrong);
  if (branding.border) root.style.setProperty("--border", branding.border);
  if (branding.borderStrong) root.style.setProperty("--border-strong", branding.borderStrong);
  // Semantic tokens — consumed via Tailwind theme extensions in
  // tailwind.config.cjs (e.g. bg-success-soft → var(--success-bg)).
  root.style.setProperty("--success-bg", branding.successBg);
  root.style.setProperty("--success-fg", branding.successFg);
  root.style.setProperty("--success-border", branding.successBorder);
  root.style.setProperty("--warning-bg", branding.warningBg);
  root.style.setProperty("--warning-fg", branding.warningFg);
  root.style.setProperty("--warning-border", branding.warningBorder);
  root.style.setProperty("--danger-bg", branding.dangerBg);
  root.style.setProperty("--danger-fg", branding.dangerFg);
  root.style.setProperty("--danger-border", branding.dangerBorder);
  root.style.setProperty("--info-bg", branding.infoBg);
  root.style.setProperty("--info-fg", branding.infoFg);
  root.style.setProperty("--info-border", branding.infoBorder);
  root.style.setProperty("--neutral-bg", branding.neutralBg);
  root.style.setProperty("--neutral-fg", branding.neutralFg);
  root.style.setProperty("--neutral-border", branding.neutralBorder);
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
