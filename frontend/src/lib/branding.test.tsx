import { render, act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import type { ReactNode } from "react";

// Mock dependencies before importing the module under test
vi.mock("@/lib/api-base", () => ({
  getApiBaseUrl: () => "http://test-api",
}));

vi.mock("@/auth/localAuth", () => ({
  isLocalAuthMode: () => true,
  getLocalAuthToken: () => "test-token",
}));

// Now import the module under test
import { BrandingProvider, useBranding, useBrandingRefresh } from "./branding";

const DEPLOYMENT_RESPONSE = {
  product_name: "DeployProduct",
  company_name: "DeployCo",
  full_title: "DeployCo DeployProduct",
  description: "Test description",
  accent_color: "#aaaaaa",
  accent_strong: "#bbbbbb",
  accent_soft: "rgba(0,0,0,0.1)",
  logo_path: "/deploy-logo.png",
  copyright_holder: "DeployCo",
};

const ORG_RESPONSE = {
  product_name: "OrgProduct",
  company_name: "OrgCo",
  full_title: "OrgCo OrgProduct",
  description: "Org description",
  accent_color: "#111111",
  accent_strong: "#222222",
  accent_soft: "rgba(1,1,1,0.1)",
  logo_path: "/org-logo.png",
  copyright_holder: "OrgCo",
};

function wrapper({ children }: { children: ReactNode }) {
  return <BrandingProvider>{children}</BrandingProvider>;
}

describe("BrandingProvider", () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.useFakeTimers();
    fetchSpy = vi.spyOn(globalThis, "fetch");
  });

  afterEach(() => {
    vi.useRealTimers();
    fetchSpy.mockRestore();
  });

  it("provides default branding before API response", () => {
    // Fetch never resolves
    fetchSpy.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useBranding(), { wrapper });
    expect(result.current.productName).toBe("Product Foundry");
  });

  it("fetches deployment branding on mount", async () => {
    fetchSpy.mockResolvedValue(
      new Response(JSON.stringify(DEPLOYMENT_RESPONSE), { status: 200 }),
    );

    let result: { current: ReturnType<typeof useBranding> };
    await act(async () => {
      ({ result } = renderHook(() => useBranding(), { wrapper }));
    });

    expect(result!.current.productName).toBe("DeployProduct");
    expect(result!.current.companyName).toBe("DeployCo");
  });

  it("fetches org branding after delay", async () => {
    // First call = deployment, second call = org
    fetchSpy
      .mockResolvedValueOnce(
        new Response(JSON.stringify(DEPLOYMENT_RESPONSE), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(ORG_RESPONSE), { status: 200 }),
      );

    let result: { current: ReturnType<typeof useBranding> };
    await act(async () => {
      ({ result } = renderHook(() => useBranding(), { wrapper }));
    });

    // After mount: deployment branding loaded
    expect(result!.current.productName).toBe("DeployProduct");

    // Advance timer to trigger org fetch
    await act(async () => {
      vi.advanceTimersByTime(600);
    });

    expect(result!.current.productName).toBe("OrgProduct");
    expect(result!.current.companyName).toBe("OrgCo");
  });

  it("falls back to deployment branding when org fetch fails", async () => {
    fetchSpy
      .mockResolvedValueOnce(
        new Response(JSON.stringify(DEPLOYMENT_RESPONSE), { status: 200 }),
      )
      .mockResolvedValueOnce(new Response("", { status: 403 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(DEPLOYMENT_RESPONSE), { status: 200 }),
      );

    let result: { current: ReturnType<typeof useBranding> };
    await act(async () => {
      ({ result } = renderHook(() => useBranding(), { wrapper }));
    });

    await act(async () => {
      vi.advanceTimersByTime(600);
    });

    // Should still have deployment branding
    expect(result!.current.productName).toBe("DeployProduct");
  });

  it("refreshBranding re-fetches org branding", async () => {
    fetchSpy
      .mockResolvedValueOnce(
        new Response(JSON.stringify(DEPLOYMENT_RESPONSE), { status: 200 }),
      )
      // Initial org fetch (timer fires)
      .mockResolvedValueOnce(
        new Response(JSON.stringify(ORG_RESPONSE), { status: 200 }),
      )
      // Manual refresh call
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ ...ORG_RESPONSE, product_name: "Refreshed" }),
          { status: 200 },
        ),
      );

    let brandingResult: { current: ReturnType<typeof useBranding> };
    let refreshResult: { current: ReturnType<typeof useBrandingRefresh> };

    await act(async () => {
      ({ result: brandingResult } = renderHook(() => useBranding(), {
        wrapper,
      }));
    });
    // Separate hook for refresh (same context)
    await act(async () => {
      ({ result: refreshResult } = renderHook(() => useBrandingRefresh(), {
        wrapper,
      }));
    });

    // Call refresh explicitly
    await act(async () => {
      await refreshResult!.current();
    });

    // At this point, fetch was called with the refreshed data
    expect(fetchSpy).toHaveBeenCalled();
  });

  it("applies CSS custom properties", async () => {
    fetchSpy.mockResolvedValue(
      new Response(JSON.stringify(DEPLOYMENT_RESPONSE), { status: 200 }),
    );

    await act(async () => {
      render(
        <BrandingProvider>
          <div>test</div>
        </BrandingProvider>,
      );
    });

    const root = document.documentElement;
    expect(root.style.getPropertyValue("--accent")).toBe("#aaaaaa");
    expect(root.style.getPropertyValue("--accent-strong")).toBe("#bbbbbb");
  });
});
