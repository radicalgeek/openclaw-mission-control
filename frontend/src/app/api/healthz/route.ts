import { NextResponse } from "next/server";

/**
 * Lightweight health-check endpoint used by Kubernetes liveness and readiness
 * probes. Returns immediately without performing any SSR or data fetching so
 * the response is fast even during cold-start and the probe timeout is reliable.
 */
export function GET(): NextResponse {
  return NextResponse.json({ status: "ok" });
}
