import { NextResponse } from "next/server";

/**
 * Proxy /api/branding → backend /api/v1/branding.
 *
 * Fetching branding server-side avoids CORS issues when the browser would
 * otherwise make a cross-origin request to the backend container directly.
 *
 * Resolution order for the upstream URL:
 *   1. BACKEND_URL  — set this on the container to the internal service address
 *      (e.g. http://ca-axiacraft-backend on ACA). Never baked into the client bundle.
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

export async function GET(): Promise<NextResponse> {
  const backendUrl = resolveBackendUrl();
  if (!backendUrl) {
    return NextResponse.json(
      { error: "BACKEND_URL is not configured on the frontend container." },
      { status: 502 },
    );
  }

  try {
    const res = await fetch(`${backendUrl}/api/v1/branding`, {
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json(
        { error: "Upstream branding fetch failed", status: res.status },
        { status: res.status },
      );
    }
    const data = (await res.json()) as unknown;
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json(
      { error: "Branding proxy error", detail: String(err) },
      { status: 502 },
    );
  }
}
