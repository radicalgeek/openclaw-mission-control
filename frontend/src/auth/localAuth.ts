"use client";

import { AuthMode } from "@/auth/mode";

let localToken: string | null = null;
const STORAGE_KEY = "mc_local_auth_token";

// Cookie name must match what AuthGate reads server-side via next/headers cookies().
export const LOCAL_AUTH_COOKIE_NAME = "mc_local_auth_token";

export function isLocalAuthMode(): boolean {
  return process.env.NEXT_PUBLIC_AUTH_MODE === AuthMode.Local;
}

export function setLocalAuthToken(token: string): void {
  localToken = token;
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, token);
  } catch {
    // Ignore storage failures (private mode / policy).
  }
  try {
    // Also write an HTTP cookie so Next.js SSR/middleware can read auth state
    // server-side. Without this, SSR renders as unauthenticated and causes a
    // hydration mismatch (React error #418) on page load after login.
    document.cookie = `${LOCAL_AUTH_COOKIE_NAME}=${encodeURIComponent(token)}; path=/; SameSite=Strict`;
  } catch {
    // Ignore cookie failures.
  }
}

export function getLocalAuthToken(): string | null {
  if (localToken) return localToken;
  if (typeof window === "undefined") return null;
  try {
    const stored = window.sessionStorage.getItem(STORAGE_KEY);
    if (stored) {
      localToken = stored;
      return stored;
    }
  } catch {
    // Ignore storage failures (private mode / policy).
  }
  return null;
}

export function clearLocalAuthToken(): void {
  localToken = null;
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore storage failures (private mode / policy).
  }
  try {
    document.cookie = `${LOCAL_AUTH_COOKIE_NAME}=; path=/; max-age=0; SameSite=Strict`;
  } catch {
    // Ignore cookie failures.
  }
}
