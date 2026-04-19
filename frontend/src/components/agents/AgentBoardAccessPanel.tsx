"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useListBoardsApiV1BoardsGet } from "@/api/generated/boards/boards";
import type { BoardRead } from "@/api/generated/model";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  listAgentBoardAccess,
  createAgentBoardAccess,
  deleteAgentBoardAccess,
  type AgentBoardAccessRead,
} from "@/api/standaloneAgents";

interface Props {
  agentId: string;
}

export function AgentBoardAccessPanel({ agentId }: Props) {
  const queryClient = useQueryClient();
  const [showGrant, setShowGrant] = useState(false);
  const [boardId, setBoardId] = useState<string>("");
  const [accessLevel, setAccessLevel] = useState<"read" | "write">("read");

  const { data: accessData, isLoading: isLoadingAccess } = useQuery({
    queryKey: ["agent-board-access", agentId],
    queryFn: () => listAgentBoardAccess(agentId),
    staleTime: 30_000,
  });

  const { data: boardsData } = useListBoardsApiV1BoardsGet();
  const boards: BoardRead[] =
    boardsData?.status === 200
      ? ((boardsData.data as { items?: BoardRead[] }).items ?? [])
      : [];

  const grants: AgentBoardAccessRead[] = accessData?.data ?? [];

  // Build board name lookup
  const boardNameById = new Map(
    boards.map((b) => [String(b.id), b.name ?? `Project ${b.id}`]),
  );

  // Board IDs already granted
  const grantedBoardIds = new Set(grants.map((g) => String(g.board_id)));

  // Boards available for new grant
  const availableBoards = boards.filter(
    (b) => !grantedBoardIds.has(String(b.id)),
  );

  const grantMutation = useMutation({
    mutationFn: () =>
      createAgentBoardAccess(agentId, {
        board_id: boardId,
        access_level: accessLevel,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["agent-board-access", agentId],
      });
      setShowGrant(false);
      setBoardId("");
      setAccessLevel("read");
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (grantId: string) => deleteAgentBoardAccess(agentId, grantId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["agent-board-access", agentId],
      });
    },
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Project access
          </h2>
          <p className="text-sm text-slate-500">
            Grant this standalone agent access to specific projects.
          </p>
        </div>
        {availableBoards.length > 0 && (
          <Button size="sm" onClick={() => setShowGrant((v) => !v)}>
            {showGrant ? "Cancel" : "+ Grant access"}
          </Button>
        )}
      </div>

      {showGrant && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-900">
            Grant project access
          </h3>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-medium text-slate-700">
                Project
              </label>
              <Select value={boardId} onValueChange={setBoardId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select project" />
                </SelectTrigger>
                <SelectContent>
                  {availableBoards.map((b) => (
                    <SelectItem key={b.id} value={String(b.id)}>
                      {b.name ?? `Project ${b.id}`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-slate-700">
                Access level
              </label>
              <Select
                value={accessLevel}
                onValueChange={(v) => setAccessLevel(v as "read" | "write")}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="read">Read</SelectItem>
                  <SelectItem value="write">Write</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={() => grantMutation.mutate()}
              disabled={!boardId || grantMutation.isPending}
            >
              {grantMutation.isPending ? "Granting…" : "Grant"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowGrant(false)}
            >
              Cancel
            </Button>
          </div>
          {grantMutation.isError && (
            <p className="text-xs text-red-600">
              Failed to grant access. Please try again.
            </p>
          )}
        </div>
      )}

      {isLoadingAccess ? (
        <p className="text-sm text-slate-500">Loading project access…</p>
      ) : grants.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center">
          <p className="text-sm text-slate-500">No project access granted yet.</p>
          <p className="text-xs text-slate-400 mt-1">
            Grant access to projects above to let this agent read or write project
            data.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {grants.map((grant) => (
            <div
              key={grant.id}
              className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3"
            >
              <div>
                <p className="text-sm font-medium text-slate-900">
                  {boardNameById.get(String(grant.board_id)) ??
                    `Project ${grant.board_id}`}
                </p>
                <p className="text-xs text-slate-500">
                  ID: {grant.board_id}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <span
                  className={[
                    "inline-flex h-5 items-center rounded-full px-2 text-xs font-semibold",
                    grant.access_level === "write"
                      ? "bg-amber-100 text-amber-700"
                      : "bg-slate-100 text-slate-600",
                  ].join(" ")}
                >
                  {grant.access_level === "write" ? "Write" : "Read"}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-red-600 hover:text-red-700"
                  onClick={() => revokeMutation.mutate(grant.id)}
                  disabled={revokeMutation.isPending}
                >
                  Revoke
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
