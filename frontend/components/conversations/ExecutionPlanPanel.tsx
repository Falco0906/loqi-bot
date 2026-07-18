"use client";

import { useState, useEffect } from "react";
import Icon from "../shared/Icon";
import { getConversationPlan } from "../../lib/api";

type Props = {
  conversationId: string;
  sessionToken: string;
};

type GraphNode = {
  id: string;
  type: string;
  status: string;
  label: string;
  dependencies: string[];
  approval: string;
};

type GraphEdge = {
  source: string;
  target: string;
};

type ValidationIssue = {
  severity: string;
  code: string;
  message: string;
  task_id: string;
};

type PlanData = {
  plan: Record<string, unknown> | null;
  graph: { nodes: GraphNode[]; edges: GraphEdge[] } | null;
  explainability: Record<string, unknown> | null;
  validation: { valid: boolean; issues: ValidationIssue[]; warnings: ValidationIssue[] } | null;
};

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  ready: "bg-green-500/20 text-green-400 border-green-500/30",
  blocked: "bg-red-500/20 text-red-400 border-red-500/30",
  completed: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  awaiting_approval: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  failed: "bg-red-500/20 text-red-400 border-red-500/30",
  skipped: "bg-surface-high/30 text-on-surface-variant/50 border-outline-variant/20",
};

const TASK_ICONS: Record<string, string> = {
  send_message: "send",
  send_email: "mail",
  schedule_meeting: "calendar_today",
  wait_for_reply: "forum",
  wait_duration: "schedule",
  request_approval: "check_circle",
  update_crm: "database",
  analyze_reply: "psychology",
  escalate: "warning",
  branch: "call_split",
  join: "merge",
};

export default function ExecutionPlanPanel({ conversationId, sessionToken }: Props) {
  const [planData, setPlanData] = useState<PlanData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [showValidation, setShowValidation] = useState(false);

  useEffect(() => {
    if (!sessionToken || !conversationId) return;
    setLoading(true);
    setError(null);
    getConversationPlan(sessionToken, conversationId)
      .then((res) => {
        if (res.ok && res.plan) {
          setPlanData({
            plan: res.plan,
            graph: res.graph,
            explainability: res.explainability,
            validation: res.validation,
          });
        } else {
          setPlanData(null);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load plan"))
      .finally(() => setLoading(false));
  }, [sessionToken, conversationId]);

  const hasIssues = (planData?.validation?.issues?.length ?? 0) > 0;
  const hasWarnings = (planData?.validation?.warnings?.length ?? 0) > 0;
  const planValid = planData?.validation?.valid ?? false;

  return (
    <div className="rounded-xl border border-outline-variant/10 bg-charcoal/50 p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon name="account_tree" className="text-sm text-primary" />
          <span className="text-xs font-semibold text-on-surface-variant/70 uppercase tracking-wider">
            Execution Plan
          </span>
        </div>
        {planData?.plan && (
          <span className="text-[10px] text-on-surface-variant/50">
            v{planData.plan.version as string}
          </span>
        )}
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-6">
          <span className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-3 py-2 text-[11px] text-red-400">
          {error}
        </div>
      )}

      {/* No plan */}
      {!loading && !error && !planData?.plan && (
        <div className="flex flex-col items-center py-6 text-center">
          <Icon name="account_tree" className="text-xl text-on-surface-variant/20 mb-2" />
          <p className="text-[11px] text-on-surface-variant/50">No execution plan available</p>
        </div>
      )}

      {/* Plan content */}
      {planData?.plan && !loading && (
        <>
          {/* Goal */}
          {planData.explainability && (
            <div>
              <div className="text-[10px] text-on-surface-variant/50 uppercase tracking-wider mb-1.5">Goal</div>
              <div className="rounded-lg bg-surface-high/20 border border-outline-variant/10 px-3 py-2">
                <p className="text-xs text-on-surface/80">
                  {(planData.explainability.goal as Record<string, unknown>)?.outcome as string || ""}
                </p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[10px] text-on-surface-variant/50">Strategy:</span>
                  <span className="text-[10px] font-medium text-primary px-1.5 py-0.5 rounded bg-primary/10">
                    {planData.explainability.strategy as string}
                  </span>
                  <span className="text-[10px] text-on-surface-variant/50">
                    {(planData.explainability.goal as Record<string, unknown>)?.priority as string}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Task graph */}
          {planData.graph && planData.graph.nodes.length > 0 && (
            <div>
              <div className="text-[10px] text-on-surface-variant/50 uppercase tracking-wider mb-1.5">
                Workflow ({planData.graph.nodes.length} tasks)
              </div>
              <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
                {planData.graph.nodes.map((node) => {
                  const isExpanded = expandedTaskId === node.id;
                  const isRoot = node.dependencies.length === 0;
                  const task = (planData.plan?.tasks as Array<Record<string, unknown>>)?.find((t) => t.id === node.id);
                  return (
                    <div key={node.id}>
                      <button
                        onClick={() => setExpandedTaskId(isExpanded ? null : node.id)}
                        className={`w-full flex items-center gap-2 px-2.5 py-2 rounded-lg border text-left transition-colors ${
                          isExpanded
                            ? "bg-primary/5 border-primary/20"
                            : "bg-surface-high/20 border-outline-variant/10 hover:bg-surface-high/30"
                        }`}
                      >
                        <Icon
                          name={TASK_ICONS[node.type] || "more_horiz"}
                          className={`text-xs shrink-0 ${isExpanded ? "text-primary" : "text-on-surface-variant/50"}`}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className={`text-[11px] ${isExpanded ? "text-primary font-medium" : "text-on-surface/70"} truncate`}>
                              {node.label}
                            </span>
                            {node.approval !== "none" && (
                              <span className="relative group">
                                <Icon name="check_circle" className="text-[10px] text-amber-400 shrink-0" />
                                <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-0.5 rounded bg-charcoal border border-outline-variant/20 text-[9px] text-on-surface-variant/80 whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                                  Approval: {node.approval}
                                </span>
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            <span className={`text-[9px] px-1.5 py-0.5 rounded-full border ${STATUS_STYLES[node.status] || "bg-surface-high/30 text-on-surface-variant/50 border-outline-variant/20"}`}>
                              {node.status}
                            </span>
                            {isRoot && (
                              <span className="text-[9px] text-on-surface-variant/40">root</span>
                            )}
                          </div>
                        </div>
                        <Icon
                          name="chevron_right"
                          className={`text-xs text-on-surface-variant/40 transition-transform ${isExpanded ? "rotate-90" : ""}`}
                        />
                      </button>
                      {/* Expanded task detail */}
                      {isExpanded && task && (
                        <div className="ml-5 mt-1 mb-1.5 px-3 py-2 rounded-lg bg-surface-high/10 border border-outline-variant/5 space-y-1.5">
                          {task.reasoning_trace as string && (
                            <div>
                              <span className="text-[9px] text-on-surface-variant/40 uppercase">Why:</span>
                              <p className="text-[10px] text-on-surface-variant/70 mt-0.5">{task.reasoning_trace as string}</p>
                            </div>
                          )}
                          {task.reasoning_goal as string && (
                            <div>
                              <span className="text-[9px] text-on-surface-variant/40 uppercase">Goal:</span>
                              <p className="text-[10px] text-on-surface-variant/70 mt-0.5">{task.reasoning_goal as string}</p>
                            </div>
                          )}
                          {task.instructions as string && (
                            <div>
                              <span className="text-[9px] text-on-surface-variant/40 uppercase">Instructions:</span>
                              <p className="text-[10px] text-on-surface-variant/70 mt-0.5 line-clamp-3">{task.instructions as string}</p>
                            </div>
                          )}
                          {node.dependencies.length > 0 && (
                            <div>
                              <span className="text-[9px] text-on-surface-variant/40 uppercase">Depends on:</span>
                              <div className="flex flex-wrap gap-1 mt-0.5">
                                {node.dependencies.map((depId) => {
                                  const depNode = planData.graph?.nodes.find((n) => n.id === depId);
                                  return (
                                    <span
                                      key={depId}
                                      className="text-[9px] px-1.5 py-0.5 rounded bg-outline-variant/10 text-on-surface-variant/60"
                                    >
                                      {depNode?.label || depId.slice(0, 8)}
                                    </span>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                          {node.approval !== "none" && (
                            <div className="flex items-center gap-1">
                              <Icon name="check_circle" className="text-[10px] text-amber-400" />
                              <span className="text-[9px] text-amber-400/80 uppercase">Approval: {node.approval}</span>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Validation */}
          {(hasIssues || hasWarnings) && (
            <div>
              <button
                onClick={() => setShowValidation(!showValidation)}
                className="flex items-center gap-1.5 text-[10px] text-on-surface-variant/60 hover:text-on-surface-variant/80 transition-colors"
              >
                <Icon
                  name={planValid ? "check_circle" : "warning"}
                  className={`text-xs ${planValid ? "text-green-400" : "text-amber-400"}`}
                />
                <span>
                  {planValid ? "Plan valid" : `${planData.validation!.issues.length} issue(s)`}
                  {hasWarnings && `, ${planData.validation!.warnings.length} warning(s)`}
                </span>
                <Icon name="chevron_right" className={`text-xs transition-transform ${showValidation ? "rotate-90" : ""}`} />
              </button>
              {showValidation && (
                <div className="mt-2 space-y-1 max-h-[200px] overflow-y-auto">
                  {planData.validation!.issues.map((issue, i) => (
                    <div
                      key={`issue-${i}`}
                      className="flex items-start gap-1.5 px-2 py-1.5 rounded bg-red-500/5"
                    >
                      <Icon name="error" className="text-[10px] text-red-400 mt-0.5 shrink-0" />
                      <div>
                        <p className="text-[10px] text-red-300">{issue.message}</p>
                        <span className="text-[9px] text-red-400/60">{issue.code}</span>
                      </div>
                    </div>
                  ))}
                  {planData.validation!.warnings.map((warn, i) => (
                    <div
                      key={`warn-${i}`}
                      className="flex items-start gap-1.5 px-2 py-1.5 rounded bg-amber-500/5"
                    >
                      <Icon name="warning" className="text-[10px] text-amber-400 mt-0.5 shrink-0" />
                      <div>
                        <p className="text-[10px] text-amber-300">{warn.message}</p>
                        <span className="text-[9px] text-amber-400/60">{warn.code}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Explainability chain */}
          {planData.explainability && (
            <div>
              <button
                onClick={() => setExpandedTaskId(expandedTaskId === "__explain__" ? null : "__explain__")}
                className="flex items-center gap-1.5 text-[10px] text-on-surface-variant/60 hover:text-on-surface-variant/80 transition-colors"
              >
                <Icon name="psychology" className="text-xs text-purple-400" />
                <span>Reasoning trace ({planData.explainability.total_tasks as number} tasks)</span>
                <Icon
                  name="chevron_right"
                  className={`text-xs transition-transform ${expandedTaskId === "__explain__" ? "rotate-90" : ""}`}
                />
              </button>
              {expandedTaskId === "__explain__" && (
                <div className="mt-2 space-y-2 max-h-[300px] overflow-y-auto">
                  {(planData.explainability.task_chain as Array<Record<string, unknown>>)?.map((task, i) => (
                    <div key={i} className="flex gap-2">
                      <div className="flex flex-col items-center">
                        <div className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/10">
                          <span className="text-[8px] text-primary font-medium">{i + 1}</span>
                        </div>
                        {i < ((planData.explainability?.task_chain as Array<unknown>)?.length ?? 0) - 1 && (
                          <div className="w-px flex-1 bg-outline-variant/10 min-h-[12px]" />
                        )}
                      </div>
                      <div className="pb-2">
                        <p className="text-[10px] text-on-surface-variant/80 font-medium">{task.label as string}</p>
                        <p className="text-[9px] text-on-surface-variant/50 mt-0.5">{task.reason as string}</p>
                        <div className="flex items-center gap-1.5 mt-1">
                          <span className="text-[8px] px-1 py-0.5 rounded bg-outline-variant/10 text-on-surface-variant/50">
                            {task.type as string}
                          </span>
                          {task.approval as string !== "none" && (
                            <span className="text-[8px] px-1 py-0.5 rounded bg-amber-500/10 text-amber-400">
                              approval: {task.approval as string}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
