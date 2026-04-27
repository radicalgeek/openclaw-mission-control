"use client";

import { ClerkProvider } from "@clerk/nextjs";
import { useEffect, type ReactNode } from "react";

import { isLikelyValidClerkPublishableKey } from "@/auth/clerkKey";
import {
  clearLocalAuthToken,
  getLocalAuthToken,
  isLocalAuthMode,
} from "@/auth/localAuth";
import { LocalAuthLogin } from "@/components/organisms/LocalAuthLogin";

export function AuthProvider({
  children,
  initialLocalToken = null,
}: {
  children: ReactNode;
  // Server-read cookie value forwarded from AuthGate. Providing this ensures
  // the SSR and client initial renders agree on auth state, avoiding the
  // React hydration mismatch (error #418) that occurred when SSR returned
  // null from sessionStorage-only getLocalAuthToken().
  initialLocalToken?: string | null;
}) {
  const localMode = isLocalAuthMode();

  useEffect(() => {
    if (!localMode) {
      clearLocalAuthToken();
    }
  }, [localMode]);

  if (localMode) {
    // Prefer the server-read cookie value (consistent between SSR and hydration)
    // over the client sessionStorage value (unavailable during SSR).
    const token = initialLocalToken ?? getLocalAuthToken();
    if (!token) {
      return <LocalAuthLogin />;
    }
    return <>{children}</>;
  }

  const publishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  const afterSignOutUrl =
    process.env.NEXT_PUBLIC_CLERK_AFTER_SIGN_OUT_URL ?? "/";

  if (!isLikelyValidClerkPublishableKey(publishableKey)) {
    return <>{children}</>;
  }

  return (
    <ClerkProvider
      publishableKey={publishableKey}
      afterSignOutUrl={afterSignOutUrl}
    >
      {children}
    </ClerkProvider>
  );
}
