"use client";

export const dynamic = "force-dynamic";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/auth/clerk";
import { ApiError } from "@/api/mutator";
import {
  type listBoardsApiV1BoardsGetResponse,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { SignInButton, SignedIn, SignedOut } from "@/auth/clerk";
import { Button } from "@/components/ui/button";

export default function ChannelsIndexPage() {
  const router = useRouter();
  const { isSignedIn } = useAuth();
  const [redirected, setRedirected] = useState(false);

  const boardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn),
      refetchOnMount: "always",
    },
  });

  const boards =
    boardsQuery.data?.status === 200
      ? (boardsQuery.data.data.items ?? [])
      : [];

  useEffect(() => {
    if (redirected) return;
    if (!boardsQuery.isSuccess) return;
    if (boards.length === 0) return;
    const first = boards[0];
    setRedirected(true);
    router.replace(`/channels/${first.id}`);
  }, [boardsQuery.isSuccess, boards, redirected, router]);

  return (
    <DashboardShell>
      <SignedOut>
        <div className="flex h-full flex-col items-center justify-center gap-4 rounded-2xl p-10 text-center">
          <p className="text-sm text-slate-500">Sign in to view channels.</p>
          <SignInButton
            mode="modal"
            forceRedirectUrl="/channels"
            signUpForceRedirectUrl="/channels"
          >
            <Button>Sign in</Button>
          </SignInButton>
        </div>
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-y-auto bg-[color:var(--bg)]">
          <div className="flex h-full items-center justify-center">
            {boardsQuery.isLoading ? (
              <p className="text-sm text-slate-500">Loading channels…</p>
            ) : boards.length === 0 ? (
              <div className="text-center">
                <p className="text-sm font-semibold text-slate-700">
                  No boards found
                </p>
                <p className="mt-1 text-sm text-slate-500">
                  Create a board to start using channels.
                </p>
              </div>
            ) : (
              <p className="text-sm text-slate-500">Redirecting…</p>
            )}
          </div>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}
