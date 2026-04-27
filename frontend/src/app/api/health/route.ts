import { NextResponse } from "next/server";

/**
 * Alias of /api/healthz for clients that probe /api/health.
 */
export function GET(): NextResponse {
  return NextResponse.json({ status: "ok" });
}
