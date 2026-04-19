"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  listAgentWebhooks,
  createAgentWebhook,
  updateAgentWebhook,
  deleteAgentWebhook,
  listAgentWebhookPayloads,
  type AgentWebhookRead,
  type AgentWebhookPayloadRead,
} from "@/api/standaloneAgents";

interface Props {
  agentId: string;
}

function PayloadsDrawer({
  agentId,
  webhookId,
  onClose,
}: {
  agentId: string;
  webhookId: string;
  onClose: () => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["agent-webhook-payloads", agentId, webhookId],
    queryFn: () => listAgentWebhookPayloads(agentId, webhookId),
    staleTime: 30_000,
  });

  const payloads: AgentWebhookPayloadRead[] = data?.data?.items ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center">
      <div
        className="fixed inset-0 bg-black/40"
        onClick={onClose}
        aria-hidden
      />
      <div className="relative z-10 w-full max-w-2xl rounded-t-2xl sm:rounded-2xl bg-white shadow-xl p-6 max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-slate-900">
            Recent payloads
          </h3>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
        {isLoading ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : payloads.length === 0 ? (
          <p className="text-sm text-slate-500">No payloads received yet.</p>
        ) : (
          <div className="overflow-y-auto space-y-3 flex-1">
            {payloads.map((p) => (
              <div
                key={p.id}
                className="rounded-lg border border-slate-200 p-3 space-y-1"
              >
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <span className="font-mono">{p.received_at}</span>
                </div>
                <pre className="text-xs bg-slate-50 rounded p-2 overflow-x-auto max-h-40">
                  {JSON.stringify(p.payload, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

interface WebhookRowProps {
  agentId: string;
  webhook: AgentWebhookRead;
}

function WebhookRow({ agentId, webhook }: WebhookRowProps) {
  const queryClient = useQueryClient();
  const [showPayloads, setShowPayloads] = useState(false);
  const [editing, setEditing] = useState(false);
  const [description, setDescription] = useState(
    webhook.description ?? "",
  );
  const [secret, setSecret] = useState("");
  const [signatureHeader, setSignatureHeader] = useState(
    webhook.signature_header ?? "",
  );

  const updateMutation = useMutation({
    mutationFn: (data: Parameters<typeof updateAgentWebhook>[2]) =>
      updateAgentWebhook(agentId, webhook.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["agent-webhooks", agentId],
      });
      setEditing(false);
      setSecret("");
    },
  });

  const toggleMutation = useMutation({
    mutationFn: () =>
      updateAgentWebhook(agentId, webhook.id, {
        enabled: !webhook.enabled,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["agent-webhooks", agentId],
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteAgentWebhook(agentId, webhook.id),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["agent-webhooks", agentId],
      });
    },
  });

  const handleUpdate = () => {
    updateMutation.mutate({
      description: description || undefined,
      secret: secret || undefined,
      signature_header: signatureHeader || undefined,
    });
  };

  return (
    <>
      {showPayloads && (
        <PayloadsDrawer
          agentId={agentId}
          webhookId={webhook.id}
          onClose={() => setShowPayloads(false)}
        />
      )}
      <div className="rounded-xl border border-slate-200 p-4 space-y-3">
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className={[
                  "inline-flex h-5 items-center rounded-full px-2 text-xs font-semibold",
                  webhook.enabled
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-slate-100 text-slate-500",
                ].join(" ")}
              >
                {webhook.enabled ? "Active" : "Disabled"}
              </span>
              {webhook.has_secret && (
                <span className="inline-flex h-5 items-center rounded-full bg-amber-100 text-amber-700 px-2 text-xs font-semibold">
                  🔑 Secret set
                </span>
              )}
            </div>
            <p className="mt-1 font-mono text-xs text-slate-700 break-all">
              {webhook.endpoint_url}
            </p>
            {webhook.description && (
              <p className="text-sm text-slate-600 mt-1">
                {webhook.description}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowPayloads(true)}
            >
              Payloads
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => toggleMutation.mutate()}
              disabled={toggleMutation.isPending}
            >
              {webhook.enabled ? "Disable" : "Enable"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setEditing((v) => !v)}
            >
              Edit
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-red-600 hover:text-red-700"
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
            >
              Delete
            </Button>
          </div>
        </div>
        {editing && (
          <div className="mt-2 space-y-3 border-t border-slate-100 pt-3">
            <div className="space-y-1">
              <label className="text-xs font-medium text-slate-700">
                Description
              </label>
              <Input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional description"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs font-medium text-slate-700">
                  New secret (leave blank to keep)
                </label>
                <Input
                  type="password"
                  value={secret}
                  onChange={(e) => setSecret(e.target.value)}
                  placeholder="e.g. mysecret123"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-slate-700">
                  Signature header
                </label>
                <Input
                  value={signatureHeader}
                  onChange={(e) => setSignatureHeader(e.target.value)}
                  placeholder="X-Hub-Signature-256"
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={handleUpdate}
                disabled={updateMutation.isPending}
              >
                {updateMutation.isPending ? "Saving…" : "Save"}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setEditing(false);
                  setSecret("");
                }}
              >
                Cancel
              </Button>
            </div>
            {updateMutation.isError && (
              <p className="text-xs text-red-600">
                Failed to update webhook. Please try again.
              </p>
            )}
          </div>
        )}
      </div>
    </>
  );
}

export function AgentWebhooksPanel({ agentId }: Props) {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [description, setDescription] = useState("");
  const [secret, setSecret] = useState("");
  const [signatureHeader, setSignatureHeader] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["agent-webhooks", agentId],
    queryFn: () => listAgentWebhooks(agentId),
    staleTime: 30_000,
  });

  const webhooks: AgentWebhookRead[] = data?.data ?? [];

  const createMutation = useMutation({
    mutationFn: () =>
      createAgentWebhook(agentId, {
        description: description || undefined,
        secret: secret || undefined,
        signature_header: signatureHeader || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["agent-webhooks", agentId],
      });
      setShowCreate(false);
      setDescription("");
      setSecret("");
      setSignatureHeader("");
    },
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Webhooks</h2>
          <p className="text-sm text-slate-500">
            Inbound HTTP endpoints that trigger this agent.
          </p>
        </div>
        <Button size="sm" onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? "Cancel" : "+ New webhook"}
        </Button>
      </div>

      {showCreate && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-900">
            Create webhook
          </h3>
          <div className="space-y-1">
            <label className="text-xs font-medium text-slate-700">
              Description
            </label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional — e.g. GitHub push"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-medium text-slate-700">
                Secret (optional)
              </label>
              <Input
                type="password"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                placeholder="Signing secret"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-slate-700">
                Signature header
              </label>
              <Input
                value={signatureHeader}
                onChange={(e) => setSignatureHeader(e.target.value)}
                placeholder="X-Hub-Signature-256"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={() => createMutation.mutate()}
              disabled={createMutation.isPending}
            >
              {createMutation.isPending ? "Creating…" : "Create"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowCreate(false)}
            >
              Cancel
            </Button>
          </div>
          {createMutation.isError && (
            <p className="text-xs text-red-600">
              Failed to create webhook. Please try again.
            </p>
          )}
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-slate-500">Loading webhooks…</p>
      ) : webhooks.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center">
          <p className="text-sm text-slate-500">No webhooks yet.</p>
          <p className="text-xs text-slate-400 mt-1">
            Create one above to get an inbound URL for this agent.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {webhooks.map((wh) => (
            <WebhookRow key={wh.id} agentId={agentId} webhook={wh} />
          ))}
        </div>
      )}
    </div>
  );
}
