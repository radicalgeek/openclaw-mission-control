"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { getApiBaseUrl } from "@/lib/api-base";
import { isLocalAuthMode, getLocalAuthToken } from "@/auth/localAuth";

export interface BrandingConfig {
  productName: string;
  companyName: string;
  fullTitle: string;
  description: string;
  accentColor: string;
  accentStrong: string;
  accentSoft: string;
  logoPath: string;
  copyrightHolder: string;
}

const DEFAULTS: BrandingConfig = {
  productName: "Product Foundry",
  companyName: "AxiaCraft",
  fullTitle: "AxiaCraft Product Foundry",
  description: "AI product engineering command center.",
  accentColor: "#c9972a",
  accentStrong: "#d4a82e",
  accentSoft: "rgba(201, 151, 42, 0.18)",
  logoPath: "/axiacraft-logo.png",
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
    logoPath: raw.logo_path,
    copyrightHolder: raw.copyright_holder,
  };
}

async function fetchDeploymentBranding(): Promise<BrandingConfig> {
  try {
    const url = `${getApiBaseUrl()}/api/v1/branding`;
    const res = await fetch(url, { cache: "no-store" });
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
    const url = `${getApiBaseUrl()}/api/v1/organizations/me/branding`;
    const res = await fetch(url, {
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
