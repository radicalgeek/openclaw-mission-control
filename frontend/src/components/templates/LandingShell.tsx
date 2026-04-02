"use client";

import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

import {
  SignInButton,
  SignedIn,
  SignedOut,
  isClerkEnabled,
} from "@/auth/clerk";

import { UserMenu } from "@/components/organisms/UserMenu";

export function LandingShell({ children }: { children: ReactNode }) {
  const clerkEnabled = isClerkEnabled();

  return (
    <div className="landing-enterprise">
      <nav className="landing-nav" aria-label="Primary navigation">
        <div className="nav-container">
          <Link href="/" className="logo-section" aria-label="AxiaCraft ProductFoundry home">
            <Image
              src="/axiacraft-logo.png"
              alt="AxiaCraft ProductFoundry"
              width={2018}
              height={1042}
              className="h-10 w-auto"
              priority
            />
          </Link>

          <div className="nav-links">
            <Link href="#capabilities">Capabilities</Link>
            <Link href="/boards">Boards</Link>
            <Link href="/activity">Activity</Link>
            <Link href="/gateways">Gateways</Link>
          </div>

          <div className="nav-cta">
            <SignedOut>
              {clerkEnabled ? (
                <>
                  <SignInButton
                    mode="modal"
                    forceRedirectUrl="/onboarding"
                    signUpForceRedirectUrl="/onboarding"
                  >
                    <button type="button" className="btn-secondary">
                      Sign In
                    </button>
                  </SignInButton>
                  <SignInButton
                    mode="modal"
                    forceRedirectUrl="/onboarding"
                    signUpForceRedirectUrl="/onboarding"
                  >
                    <button type="button" className="btn-primary">
                      Start Free Trial
                    </button>
                  </SignInButton>
                </>
              ) : (
                <>
                  <Link href="/boards" className="btn-secondary">
                    Boards
                  </Link>
                  <Link href="/onboarding" className="btn-primary">
                    Get started
                  </Link>
                </>
              )}
            </SignedOut>

            <SignedIn>
              <Link href="/boards/new" className="btn-secondary">
                Create Board
              </Link>
              <Link href="/boards" className="btn-primary">
                Open Boards
              </Link>
              <UserMenu />
            </SignedIn>
          </div>
        </div>
      </nav>

      <main>{children}</main>

      <footer className="landing-footer">
        <div className="footer-content">
          <div className="footer-brand">
            <h3>AxiaCraft ProductFoundry</h3>
            <p>AI product engineering command center for agents, boards, and delivery.</p>
            <div className="footer-tagline">Autonomous Engineering Delivery</div>
          </div>

          <div className="footer-column">
            <h4>Product</h4>
            <div className="footer-links">
              <Link href="#capabilities">Capabilities</Link>
              <Link href="/boards">Boards</Link>
              <Link href="/activity">Activity</Link>
              <Link href="/dashboard">Dashboard</Link>
            </div>
          </div>

          <div className="footer-column">
            <h4>Platform</h4>
            <div className="footer-links">
              <Link href="/gateways">Gateways</Link>
              <Link href="/agents">Agents</Link>
              <Link href="/dashboard">Dashboard</Link>
            </div>
          </div>

          <div className="footer-column">
            <h4>Access</h4>
            <div className="footer-links">
              <SignedOut>
                {clerkEnabled ? (
                  <>
                    <SignInButton
                      mode="modal"
                      forceRedirectUrl="/onboarding"
                      signUpForceRedirectUrl="/onboarding"
                    >
                      <button type="button">Sign In</button>
                    </SignInButton>
                    <SignInButton
                      mode="modal"
                      forceRedirectUrl="/onboarding"
                      signUpForceRedirectUrl="/onboarding"
                    >
                      <button type="button">Create Account</button>
                    </SignInButton>
                  </>
                ) : (
                  <Link href="/boards">Boards</Link>
                )}
                <Link href="/onboarding">Onboarding</Link>
              </SignedOut>
              <SignedIn>
                <Link href="/boards">Open Boards</Link>
                <Link href="/boards/new">Create Board</Link>
                <Link href="/dashboard">Dashboard</Link>
              </SignedIn>
            </div>
          </div>
        </div>

        <div className="footer-bottom">
          <div className="footer-copyright">
            © {new Date().getFullYear()} AxiaCraft. All rights reserved.
          </div>
          <div className="footer-bottom-links">
            <Link href="#capabilities">Capabilities</Link>
            <Link href="/boards">Boards</Link>
            <Link href="/activity">Activity</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
