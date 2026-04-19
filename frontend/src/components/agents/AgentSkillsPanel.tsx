"use client";

import { useState, KeyboardEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getAgentSkills,
  updateAgentSkills,
} from "@/api/standaloneAgents";

interface Props {
  agentId: string;
}

export function AgentSkillsPanel({ agentId }: Props) {
  const queryClient = useQueryClient();
  const [newSkill, setNewSkill] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["agent-skills", agentId],
    queryFn: () => getAgentSkills(agentId),
    staleTime: 60_000,
  });

  // null means "inherit gateway defaults"
  const installedSkills: string[] | null = data?.data?.installed_skills ?? null;
  const displaySkills: string[] = installedSkills ?? [];

  const mutation = useMutation({
    mutationFn: (skills: string[] | null) =>
      updateAgentSkills(agentId, { installed_skills: skills }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent-skills", agentId] });
    },
  });

  const handleAdd = () => {
    const trimmed = newSkill.trim();
    if (!trimmed || displaySkills.includes(trimmed)) return;
    mutation.mutate([...displaySkills, trimmed]);
    setNewSkill("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAdd();
    }
  };

  const handleRemove = (skill: string) => {
    const updated = displaySkills.filter((s) => s !== skill);
    mutation.mutate(updated.length > 0 ? updated : null);
  };

  const handleResetToDefaults = () => {
    mutation.mutate(null);
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-slate-900">
          Skill allowlist
        </h2>
        <p className="text-sm text-slate-500">
          Restrict which skills this agent can invoke. When set to{" "}
          <span className="font-mono text-xs bg-slate-100 px-1 rounded">
            null
          </span>{" "}
          (gateway defaults), the agent inherits the skills enabled on its
          gateway.
        </p>
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-500">Loading skills…</p>
      ) : (
        <>
          {installedSkills === null ? (
            <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">
              Using gateway-level defaults. Add a skill below to create a custom
              allowlist.
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {displaySkills.map((skill) => (
                <span
                  key={skill}
                  className="inline-flex items-center gap-1 rounded-full bg-purple-100 px-3 py-1 text-sm font-medium text-purple-800"
                >
                  {skill}
                  <button
                    type="button"
                    onClick={() => handleRemove(skill)}
                    className="ml-1 text-purple-500 hover:text-purple-800 leading-none"
                    aria-label={`Remove ${skill}`}
                  >
                    ×
                  </button>
                </span>
              ))}
              {displaySkills.length === 0 && (
                <span className="text-sm text-slate-400 italic">
                  Allowlist is empty — agent cannot invoke any skills.
                </span>
              )}
            </div>
          )}

          <div className="flex gap-2">
            <Input
              value={newSkill}
              onChange={(e) => setNewSkill(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Skill name, e.g. web_search"
              className="max-w-xs"
              disabled={mutation.isPending}
            />
            <Button
              size="sm"
              onClick={handleAdd}
              disabled={!newSkill.trim() || mutation.isPending}
            >
              Add
            </Button>
          </div>

          {installedSkills !== null && (
            <div className="pt-2 border-t border-slate-100">
              <Button
                variant="ghost"
                size="sm"
                className="text-slate-500 hover:text-slate-700"
                onClick={handleResetToDefaults}
                disabled={mutation.isPending}
              >
                Reset to gateway defaults
              </Button>
            </div>
          )}

          {mutation.isError && (
            <p className="text-xs text-red-600">
              Failed to update skill allowlist. Please try again.
            </p>
          )}
        </>
      )}
    </div>
  );
}
