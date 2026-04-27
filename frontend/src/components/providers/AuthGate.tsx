/**
 * Server component that reads the local-auth cookie server-side and forwards
 * it to AuthProvider as `initialLocalToken`.
 *
 * This is the correct place to read auth state for SSR: `cookies()` from
 * `next/headers` is available here but not inside a "use client" component.
 * Passing the token as a prop ensures the server and client render the same
 * initial tree, eliminating the React hydration mismatch (error #418) that
 * occurred when SSR rendered "unauthenticated" and the client re-rendered
 * after reading sessionStorage.
 */

import { cookies } from "next/headers";
import type { ReactNode } from "react";

import { AuthProvider } from "./AuthProvider";

// Must stay in sync with LOCAL_AUTH_COOKIE_NAME in @/auth/localAuth.ts.
// Defined locally to avoid importing a "use client" module into a server
// component boundary.
const LOCAL_AUTH_COOKIE_NAME = "mc_local_auth_token";

export async function AuthGate({ children }: { children: ReactNode }) {
  const cookieStore = await cookies();
  const initialLocalToken =
    cookieStore.get(LOCAL_AUTH_COOKIE_NAME)?.value ?? null;

  return (
    <AuthProvider initialLocalToken={initialLocalToken}>
      {children}
    </AuthProvider>
  );
}
