"use client";

export const dynamic = "force-dynamic";

import { useParams } from "next/navigation";

import { useAuth } from "@/auth/clerk";
import { SignInButton, SignedIn, SignedOut } from "@/auth/clerk";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { ChannelsLayout } from "@/components/channels/ChannelsLayout";
import { Button } from "@/components/ui/button";

export default function ChannelsBoardPage() {
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
          <p className="text-sm text-slate-500">Sign in to view channels.</p>
          <SignInButton
            mode="modal"
            forceRedirectUrl={`/channels/${boardId}`}
            signUpForceRedirectUrl={`/channels/${boardId}`}
          >
            <Button>Sign in</Button>
          </SignInButton>
        </div>
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex min-h-0 flex-1 overflow-hidden">
          {isSignedIn && boardId ? (
            <ChannelsLayout boardId={boardId} />
          ) : null}
        </main>
      </SignedIn>
    </DashboardShell>
  );
}
