"use client";

export const dynamic = "force-dynamic";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/auth/clerk";

import { ApiError } from "@/api/mutator";
import {
  type listBoardsApiV1BoardsGetResponse,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import {
  type listGatewaysApiV1GatewaysGetResponse,
  useListGatewaysApiV1GatewaysGet,
} from "@/api/generated/gateways/gateways";
import { useCreateAgentApiV1AgentsPost } from "@/api/generated/agents/agents";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import type { BoardRead, GatewayRead } from "@/api/generated/model";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import SearchableSelect, {
  type SearchableSelectOption,
} from "@/components/ui/searchable-select";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AGENT_EMOJI_OPTIONS } from "@/lib/agent-emoji";
import { DEFAULT_IDENTITY_PROFILE } from "@/lib/agent-templates";

const BOARD_WORKER_ROLE_TEMPLATES = [
  { value: "triager", label: "Triager — decomposes plans into backlog tickets" },
  { value: "planner", label: "Planner — sprint planning and velocity tracking" },
  { value: "estimator", label: "Estimator — estimates tickets in minutes" },
  { value: "test_agent", label: "Test Agent — writes ATDD tests before implementation" },
  { value: "merger", label: "Merger — branch integration and conflict resolution" },
  { value: "ui_test", label: "UI Test — Playwright accessibility-tree tests" },
  { value: "visual_regression", label: "Visual Regression — screenshot comparison" },
] as const;

const STANDALONE_ROLE_TEMPLATES = [
  { value: "quality_reviewer", label: "Quality Reviewer — code quality go/no-go" },
  { value: "security_reviewer", label: "Security Reviewer — security vulnerability go/no-go" },
  { value: "architecture_reviewer", label: "Architecture Reviewer — structural integrity go/no-go" },
] as const;

type AgentMode = "board" | "standalone";

type IdentityProfile = {
  role: string;
  communication_style: string;
  emoji: string;
};

const getBoardOptions = (boards: BoardRead[]): SearchableSelectOption[] =>
  boards.map((board) => ({
    value: board.id,
    label: board.name,
  }));

const getGatewayOptions = (gateways: GatewayRead[]): SearchableSelectOption[] =>
  gateways.map((gw) => ({
    value: gw.id,
    label: gw.name ?? gw.id,
  }));

const normalizeIdentityProfile = (
  profile: IdentityProfile,
): IdentityProfile | null => {
  const normalized: IdentityProfile = {
    role: profile.role.trim(),
    communication_style: profile.communication_style.trim(),
    emoji: profile.emoji.trim(),
  };
  const hasValue = Object.values(normalized).some((value) => value.length > 0);
  return hasValue ? normalized : null;
};

export default function NewAgentPage() {
  const router = useRouter();
  const { isSignedIn } = useAuth();

  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const [mode, setMode] = useState<AgentMode>("board");
  const [name, setName] = useState("");
  const [boardId, setBoardId] = useState<string>("");
  const [gatewayId, setGatewayId] = useState<string>("");
  const [heartbeatEvery, setHeartbeatEvery] = useState("10m");
  const [identityProfile, setIdentityProfile] = useState<IdentityProfile>({
    ...DEFAULT_IDENTITY_PROFILE,
  });
  const [roleTemplate, setRoleTemplate] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  const boardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchOnMount: "always",
    },
  });

  const gatewaysQuery = useListGatewaysApiV1GatewaysGet<
    listGatewaysApiV1GatewaysGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchOnMount: "always",
    },
  });

  const createAgentMutation = useCreateAgentApiV1AgentsPost<ApiError>({
    mutation: {
      onSuccess: (result) => {
        if (result.status === 200) {
          router.push(`/agents/${result.data.id}`);
        }
      },
      onError: (err) => {
        setError(err.message || "Something went wrong.");
      },
    },
  });

  const boards =
    boardsQuery.data?.status === 200 ? (boardsQuery.data.data.items ?? []) : [];
  const gateways =
    gatewaysQuery.data?.status === 200 ? (gatewaysQuery.data.data.items ?? []) : [];
  const displayBoardId = boardId || boards[0]?.id || "";
  const displayGatewayId = gatewayId || gateways[0]?.id || "";
  const isLoading = boardsQuery.isLoading || gatewaysQuery.isLoading || createAgentMutation.isPending;
  const errorMessage = error ?? boardsQuery.error?.message ?? null;

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isSignedIn) return;
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Agent name is required.");
      return;
    }

    if (mode === "standalone") {
      if (!displayGatewayId) {
        setError("Select a gateway for the standalone agent.");
        return;
      }
      setError(null);
      createAgentMutation.mutate({
        data: {
          name: trimmed,
          agent_type: "standalone",
          gateway_id: displayGatewayId,
          heartbeat_config: {
            every: heartbeatEvery.trim() || "10m",
            target: "last",
            includeReasoning: false,
          },
          identity_profile: {
            ...normalizeIdentityProfile(identityProfile),
            ...(roleTemplate ? { role_template: roleTemplate } : {}),
          } as unknown as Record<string, unknown> | null,
        },
      });
      return;
    }

    const resolvedBoardId = displayBoardId;
    if (!resolvedBoardId) {
      setError("Select a project before creating an agent.");
      return;
    }
    setError(null);
    createAgentMutation.mutate({
      data: {
        name: trimmed,
        board_id: resolvedBoardId,
        heartbeat_config: {
          every: heartbeatEvery.trim() || "10m",
          target: "last",
          includeReasoning: false,
        },
        identity_profile: {
          ...normalizeIdentityProfile(identityProfile),
          ...(roleTemplate ? { role_template: roleTemplate } : {}),
        } as unknown as Record<string, unknown> | null,
      },
    });
  };

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to create an agent.",
        forceRedirectUrl: "/agents/new",
        signUpForceRedirectUrl: "/agents/new",
      }}
      title="Create agent"
      description="Agents start in provisioning until they check in."
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can create agents."
    >
      <form
        onSubmit={handleSubmit}
        className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-6"
      >
        {/* Agent type toggle */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Agent type
          </p>
          <div className="mt-3 flex gap-2">
            {(["board", "standalone"] as AgentMode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => {
                  setMode(m);
                  setRoleTemplate("");
                }}
                className={[
                  "rounded-lg px-4 py-2 text-sm font-semibold transition-colors border",
                  mode === m
                    ? m === "standalone"
                      ? "bg-purple-600 text-white border-purple-600"
                      : "bg-slate-900 text-white border-slate-900"
                    : "bg-white text-slate-600 border-slate-300 hover:border-slate-400",
                ].join(" ")}
              >
                {m === "board" ? "Project Agent" : "Standalone"}
              </button>
            ))}
          </div>
          {mode === "standalone" ? (
            <p className="mt-2 text-xs text-slate-500">
              Standalone agents are not attached to a project. They can be
              triggered by webhooks and given explicit project access grants.
            </p>
          ) : (
            <p className="mt-2 text-xs text-slate-500">
              Project agents are scoped to a single project and participate in tasks,
              approvals, and project channels.
            </p>
          )}
        </div>

        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Basic configuration
          </p>
          <div className="mt-4 space-y-6">
            <div className="grid gap-6 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Agent name <span className="text-red-500">*</span>
                </label>
                <Input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="e.g. Deploy bot"
                  disabled={isLoading}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Role
                </label>
                <Input
                  value={identityProfile.role}
                  onChange={(event) =>
                    setIdentityProfile((current) => ({
                      ...current,
                      role: event.target.value,
                    }))
                  }
                  placeholder="e.g. Founder, Social Media Manager"
                  disabled={isLoading}
                />
              </div>
            </div>
            <div className="grid gap-6 md:grid-cols-2">
              {mode === "board" ? (
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-900">
                    Project <span className="text-red-500">*</span>
                  </label>
                  <SearchableSelect
                    ariaLabel="Select project"
                    value={displayBoardId}
                    onValueChange={setBoardId}
                    options={getBoardOptions(boards)}
                    placeholder="Select project"
                    searchPlaceholder="Search projects..."
                    emptyMessage="No matching projects."
                    triggerClassName="w-full h-11 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                    contentClassName="rounded-xl border border-slate-200 shadow-lg"
                    itemClassName="px-4 py-3 text-sm text-slate-700 data-[selected=true]:bg-slate-50 data-[selected=true]:text-slate-900"
                    disabled={boards.length === 0}
                  />
                  {boards.length === 0 ? (
                    <p className="text-xs text-slate-500">
                      Create a project before adding agents.
                    </p>
                  ) : null}
                </div>
              ) : (
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-900">
                    Gateway <span className="text-red-500">*</span>
                  </label>
                  <SearchableSelect
                    ariaLabel="Select gateway"
                    value={displayGatewayId}
                    onValueChange={setGatewayId}
                    options={getGatewayOptions(gateways)}
                    placeholder="Select gateway"
                    searchPlaceholder="Search gateways..."
                    emptyMessage="No gateways available."
                    triggerClassName="w-full h-11 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900 shadow-sm focus:border-purple-500 focus:ring-2 focus:ring-purple-200"
                    contentClassName="rounded-xl border border-slate-200 shadow-lg"
                    itemClassName="px-4 py-3 text-sm text-slate-700 data-[selected=true]:bg-slate-50 data-[selected=true]:text-slate-900"
                    disabled={gateways.length === 0}
                  />
                  {gateways.length === 0 ? (
                    <p className="text-xs text-slate-500">
                      No gateways found. Set up a gateway first.
                    </p>
                  ) : null}
                </div>
              )}
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Emoji
                </label>
                <Select
                  value={identityProfile.emoji}
                  onValueChange={(value) =>
                    setIdentityProfile((current) => ({
                      ...current,
                      emoji: value,
                    }))
                  }
                  disabled={isLoading}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select emoji" />
                  </SelectTrigger>
                  <SelectContent>
                    {AGENT_EMOJI_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.glyph} {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        </div>

        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Specialist role
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Optional. Select a specialist role to assign a focused operational loop to this agent.
            Leave blank for a standard worker or standalone agent.
          </p>
          <div className="mt-3">
            <Select
              value={roleTemplate || "none"}
              onValueChange={(value) => setRoleTemplate(value === "none" ? "" : value)}
              disabled={isLoading}
            >
              <SelectTrigger>
                <SelectValue placeholder="None (standard worker)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None (standard worker)</SelectItem>
                {(mode === "board" ? BOARD_WORKER_ROLE_TEMPLATES : STANDALONE_ROLE_TEMPLATES).map(
                  (option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ),
                )}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Personality &amp; behavior
          </p>
          <div className="mt-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                Communication style
              </label>
              <Input
                value={identityProfile.communication_style}
                onChange={(event) =>
                  setIdentityProfile((current) => ({
                    ...current,
                    communication_style: event.target.value,
                  }))
                }
                disabled={isLoading}
              />
            </div>
          </div>
        </div>

        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Schedule & notifications
          </p>
          <div className="mt-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                Interval
              </label>
              <Input
                value={heartbeatEvery}
                onChange={(event) => setHeartbeatEvery(event.target.value)}
                placeholder="e.g. 10m"
                disabled={isLoading}
              />
              <p className="text-xs text-slate-500">
                How often this agent runs HEARTBEAT.md (10m, 30m, 2h).
              </p>
            </div>
          </div>
        </div>

        {errorMessage ? (
          <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-600 shadow-sm">
            {errorMessage}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={isLoading}>
            {isLoading ? "Creating…" : "Create agent"}
          </Button>
          <Button
            variant="outline"
            type="button"
            onClick={() => router.push("/agents")}
          >
            Back to agents
          </Button>
        </div>
      </form>
    </DashboardPageLayout>
  );
}
