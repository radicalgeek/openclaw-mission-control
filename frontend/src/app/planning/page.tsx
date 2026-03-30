"use client";

export const dynamic = "force-dynamic";

import { useEffect, useRef } from "react";
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

export default function PlanningIndexPage() {
  const router = useRouter();
  const { isSignedIn } = useAuth();
  const redirectedRef = useRef(false);

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
    if (redirectedRef.current) return;
    if (!boardsQuery.isSuccess) return;
    if (boards.length === 0) return;
    const first = boards[0];
    redirectedRef.current = true;
    router.replace(`/planning/${first.id}`);
  }, [boardsQuery.isSuccess, boards, router]);

  return (
    <DashboardShell>
      <SignedOut>
        <div className="flex h-full flex-col items-center justify-center gap-4 rounded-2xl p-10 text-center">
          <p className="text-sm text-slate-500">Sign in to view planning.</p>
          <SignInButton
            mode="modal"
            forceRedirectUrl="/planning"
            signUpForceRedirectUrl="/planning"
          >
            <Button>Sign in</Button>
          </SignInButton>
        </div>
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex min-h-0 flex-1 flex-col items-center justify-center bg-slate-50">
          {boards.length === 0 && boardsQuery.isSuccess ? (
            <p className="text-sm text-slate-500">
              No boards found. Create a board first.
            </p>
          ) : (
            <p className="text-sm text-slate-400">Loading…</p>
          )}
        </main>
      </SignedIn>
    </DashboardShell>
  );
}
