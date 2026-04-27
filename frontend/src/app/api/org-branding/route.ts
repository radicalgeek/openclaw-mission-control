import { NextRequest, NextResponse } from "next/server";

/**
 * Proxy /api/org-branding → backend /api/v1/organizations/me/branding.
 *
 * Forwards the Authorization header so the backend can identify the org.
 * Fetching server-side avoids cross-origin CORS issues.
 *
 * Resolution order for the upstream URL:
 *   1. BACKEND_URL  — set this on the container to the internal service address.
 *   2. NEXT_PUBLIC_API_URL — only used if it is a real URL (not "auto" / placeholder).
 */
function resolveBackendUrl(): string | null {
  const backend = process.env.BACKEND_URL?.trim();
  if (backend) return backend.replace(/\/+$/, "");
  const pub = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (pub && pub.toLowerCase() !== "auto" && pub !== "__NEXT_PUBLIC_API_URL__") {
    return pub.replace(/\/+$/, "");
  }
  return null;
}

export async function GET(req: NextRequest): Promise<NextResponse> {
  const backendUrl = resolveBackendUrl();
  if (!backendUrl) {
    return NextResponse.json(
      { error: "BACKEND_URL is not configured on the frontend container." },
      { status: 502 },
    );
  }

  const authHeader = req.headers.get("authorization");
  if (!authHeader) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const res = await fetch(`${backendUrl}/api/v1/organizations/me/branding`, {
      cache: "no-store",
      headers: { Authorization: authHeader },
    });
    if (!res.ok) {
      return NextResponse.json(
        { error: "Upstream org branding fetch failed", status: res.status },
        { status: res.status },
      );
    }
    const data = (await res.json()) as unknown;
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json(
      { error: "Org branding proxy error", detail: String(err) },
      { status: 502 },
    );
  }
}
