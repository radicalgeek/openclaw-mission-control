"use client";

export const dynamic = "force-dynamic";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/auth/clerk";
import { useQueryClient } from "@tanstack/react-query";

import { AgentsTable } from "@/components/agents/AgentsTable";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { Button } from "@/components/ui/button";
import { ConfirmActionDialog } from "@/components/ui/confirm-action-dialog";

import { ApiError } from "@/api/mutator";
import {
  type listAgentsApiV1AgentsGetResponse,
  getListAgentsApiV1AgentsGetQueryKey,
  useDeleteAgentApiV1AgentsAgentIdDelete,
  useListAgentsApiV1AgentsGet,
} from "@/api/generated/agents/agents";
import {
  type listBoardsApiV1BoardsGetResponse,
  getListBoardsApiV1BoardsGetQueryKey,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import { type AgentRead } from "@/api/generated/model";
import { createOptimisticListDeleteMutation } from "@/lib/list-delete";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { useUrlSorting } from "@/lib/use-url-sorting";

const AGENT_SORTABLE_COLUMNS = [
  "name",
  "status",
  "agent_type",
  "openclaw_session_id",
  "board_id",
  "last_seen_at",
  "updated_at",
];

type AgentTypeFilter = "all" | "standalone" | "board" | "gateway_main";

const TYPE_FILTER_TABS: { key: AgentTypeFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "standalone", label: "Standalone" },
  { key: "board", label: "Project Agents" },
  { key: "gateway_main", label: "Gateway Main" },
];

function filterAgentsByType(agents: AgentRead[], filter: AgentTypeFilter): AgentRead[] {
  if (filter === "all") return agents;
  if (filter === "standalone") return agents.filter((a) => a.agent_type === "standalone");
  if (filter === "gateway_main") return agents.filter((a) => a.agent_type === "gateway_main" || a.is_gateway_main);
  // "board" = board_worker + board_lead
  return agents.filter(
    (a) =>
      a.agent_type === "board_worker" ||
      a.agent_type === "board_lead" ||
      (!a.agent_type && !a.is_gateway_main),
  );
}

export default function AgentsPage() {
  const { isSignedIn } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();

  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const { sorting, onSortingChange } = useUrlSorting({
    allowedColumnIds: AGENT_SORTABLE_COLUMNS,
    defaultSorting: [{ id: "name", desc: false }],
    paramPrefix: "agents",
  });

  const [deleteTarget, setDeleteTarget] = useState<AgentRead | null>(null);
  const [typeFilter, setTypeFilter] = useState<AgentTypeFilter>("all");

  const boardsKey = getListBoardsApiV1BoardsGetQueryKey();
  const agentsKey = getListAgentsApiV1AgentsGetQueryKey();

  const boardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchInterval: 30_000,
      refetchOnMount: "always",
    },
  });

  const agentsQuery = useListAgentsApiV1AgentsGet<
    listAgentsApiV1AgentsGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchInterval: 15_000,
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
  const agents = useMemo(
    () =>
      agentsQuery.data?.status === 200
        ? (agentsQuery.data.data.items ?? [])
        : [],
    [agentsQuery.data],
  );

  const filteredAgents = useMemo(
    () => filterAgentsByType(agents, typeFilter),
    [agents, typeFilter],
  );

  const typeCounts = useMemo(
    () => ({
      all: agents.length,
      standalone: agents.filter((a) => a.agent_type === "standalone").length,
      board: agents.filter(
        (a) => a.agent_type === "board_worker" || a.agent_type === "board_lead" || (!a.agent_type && !a.is_gateway_main),
      ).length,
      gateway_main: agents.filter((a) => a.agent_type === "gateway_main" || a.is_gateway_main).length,
    }),
    [agents],
  );

  const deleteMutation = useDeleteAgentApiV1AgentsAgentIdDelete<
    ApiError,
    { previous?: listAgentsApiV1AgentsGetResponse }
  >(
    {
      mutation: createOptimisticListDeleteMutation<
        AgentRead,
        listAgentsApiV1AgentsGetResponse,
        { agentId: string }
      >({
        queryClient,
        queryKey: agentsKey,
        getItemId: (agent) => agent.id,
        getDeleteId: ({ agentId }) => agentId,
        onSuccess: () => {
          setDeleteTarget(null);
        },
        invalidateQueryKeys: [agentsKey, boardsKey],
      }),
    },
    queryClient,
  );

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteMutation.mutate({ agentId: deleteTarget.id });
  };

  return (
    <>
      <DashboardPageLayout
        signedOut={{
          message: "Sign in to view agents.",
          forceRedirectUrl: "/agents",
          signUpForceRedirectUrl: "/agents",
        }}
        title="Agents"
        description={`${agents.length} agent${agents.length === 1 ? "" : "s"} total.`}
        headerActions={
          agents.length > 0 ? (
            <Button onClick={() => router.push("/agents/new")}>
              New agent
            </Button>
          ) : null
        }
        isAdmin={isAdmin}
        adminOnlyMessage="Only organization owners and admins can access agents."
        stickyHeader
      >
        {agents.length > 0 ? (
          <div className="flex flex-wrap gap-1 pb-2">
            {TYPE_FILTER_TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setTypeFilter(tab.key)}
                className={[
                  "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors",
                  typeFilter === tab.key
                    ? "bg-slate-900 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200",
                ].join(" ")}
              >
                {tab.label}
                <span
                  className={[
                    "rounded-full px-1.5 py-0.5 text-[10px] font-bold leading-none",
                    typeFilter === tab.key
                      ? "bg-white/20 text-white"
                      : "bg-slate-200 text-slate-500",
                  ].join(" ")}
                >
                  {typeCounts[tab.key]}
                </span>
              </button>
            ))}
          </div>
        ) : null}
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <AgentsTable
            agents={filteredAgents}
            boards={boards}
            isLoading={agentsQuery.isLoading}
            sorting={sorting}
            onSortingChange={onSortingChange}
            showActions
            stickyHeader
            onDelete={setDeleteTarget}
            emptyState={{
              title: "No agents yet",
              description:
                "Create your first agent to start executing tasks on this project.",
              actionHref: "/agents/new",
              actionLabel: "Create your first agent",
            }}
          />
        </div>

        {agentsQuery.error ? (
          <p className="mt-4 text-sm text-red-500">
            {agentsQuery.error.message}
          </p>
        ) : null}
      </DashboardPageLayout>

      <ConfirmActionDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteTarget(null);
          }
        }}
        ariaLabel="Delete agent"
        title="Delete agent"
        description={
          <>
            This will remove {deleteTarget?.name}. This action cannot be undone.
          </>
        }
        errorMessage={deleteMutation.error?.message}
        onConfirm={handleDelete}
        isConfirming={deleteMutation.isPending}
      />
    </>
  );
}
