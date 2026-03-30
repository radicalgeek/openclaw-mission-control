"use client";

export const dynamic = "force-dynamic";

import { useParams } from "next/navigation";

import { useAuth } from "@/auth/clerk";
import { SignInButton, SignedIn, SignedOut } from "@/auth/clerk";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { PlanningLayout } from "@/components/planning/PlanningLayout";
import { Button } from "@/components/ui/button";

export default function PlanningBoardPage() {
  const params = useParams();
  const boardIdParam = params?.boardId;
  const boardId = Array.isArray(boardIdParam)
    ? boardIdParam[0]
    : boardIdParam ?? "";

  const { isSignedIn } = useAuth();

  return (
    <DashboardShell>
      <SignedOut>
        <div className="flex h-full flex-col items-center justify-center gap-4 rounded-2xl p-10 text-center">
          <p className="text-sm text-slate-500">Sign in to view planning.</p>
          <SignInButton
            mode="modal"
            forceRedirectUrl={`/planning/${boardId}`}
            signUpForceRedirectUrl={`/planning/${boardId}`}
          >
            <Button>Sign in</Button>
          </SignInButton>
        </div>
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex min-h-0 flex-1 flex-col overflow-hidden bg-slate-50 h-full max-h-full">
          {isSignedIn && boardId ? (
            <PlanningLayout boardId={boardId} />
          ) : null}
        </main>
      </SignedIn>
    </DashboardShell>
  );
}
