"use client";

export const dynamic = "force-dynamic";

import { useEffect, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "@/auth/clerk";

import { ApiError } from "@/api/mutator";
import {
  type listBoardsApiV1BoardsGetResponse,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { buttonVariants } from "@/components/ui/button";

const BOARD_SORTABLE_COLUMNS = ["name", "group", "updated_at"];

export default function BoardsPage() {
  const router = useRouter();
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const boardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn),
      refetchOnMount: "always",
    },
  });

  const boards = useMemo(
    () =>
      boardsQuery.data?.status === 200
        ? (boardsQuery.data.data.items ?? [])
        : [],
    [boardsQuery.data],
  );

  // Once we have boards, redirect straight to the first one.
  useEffect(() => {
    if (!boardsQuery.isLoading && boards.length > 0) {
      router.replace(`/boards/${boards[0].id}`);
    }
  }, [boards, boardsQuery.isLoading, router]);

  // Loading state — invisible to the user, just spinning while we redirect.
  if (boardsQuery.isLoading || boards.length > 0) {
    return null;
  }

  // No boards yet — show a create-board prompt.
  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to view boards.",
        forceRedirectUrl: "/boards",
        signUpForceRedirectUrl: "/boards",
      }}
      title="Boards"
      description="Create your first board to start routing tasks and monitoring work across agents."
      headerActions={
        isAdmin ? (
          <Link
            href="/boards/new"
            className={buttonVariants({ size: "md", variant: "primary" })}
          >
            Create board
          </Link>
        ) : null
      }
      stickyHeader
    >
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <p className="text-slate-500 text-sm mb-4">
          No boards have been created yet.
        </p>
        {isAdmin && (
          <Link
            href="/boards/new"
            className={buttonVariants({ size: "md", variant: "primary" })}
          >
            Create your first board
          </Link>
        )}
      </div>
    </DashboardPageLayout>
  );
}
