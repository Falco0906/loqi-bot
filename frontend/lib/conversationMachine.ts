import type { CopilotAction } from "./actionRegistry";

export type ConversationState = "idle" | "clarification" | "working" | "completed";

export type StepStatus = "pending" | "active" | "done" | "error";

export type ActivityStep = {
  id: string;
  text: string;
  status: StepStatus;
};

export type TaskGroupStatus = "running" | "complete" | "error";

export type TaskGroup = {
  id: string;
  title: string;
  kind: TaskKind;
  steps: ActivityStep[];
  summary: string;
  status: TaskGroupStatus;
  startedAt: number;
  completedAt: number | null;
  collapsed: boolean;
};

export type TaskKind = "research" | "briefing" | "campaign" | "inbox";

export type WorkspaceTask = {
  kind: TaskKind;
  label: string;
  workspacePath: string;
  workspaceLabel: string;
  icon: string;
};

export type TransitionEvent =
  | { type: "instruction"; kind: TaskKind | "unknown" }
  | { type: "answer" }
  | { type: "work_started" }
  | { type: "work_finished" }
  | { type: "acknowledge" };

const TRANSITIONS: Record<ConversationState, Record<TransitionEvent["type"], ConversationState>> = {
  idle: { instruction: "working", answer: "idle", work_started: "idle", work_finished: "idle", acknowledge: "idle" },
  clarification: { instruction: "working", answer: "working", work_started: "clarification", work_finished: "clarification", acknowledge: "idle" },
  working: { instruction: "working", answer: "working", work_started: "working", work_finished: "completed", acknowledge: "idle" },
  completed: { instruction: "working", answer: "completed", work_started: "completed", work_finished: "completed", acknowledge: "idle" },
};

export function nextState(from: ConversationState, event: TransitionEvent): ConversationState {
  if (event.type === "instruction" && event.kind === "unknown") return "clarification";
  return TRANSITIONS[from][event.type];
}

const KEYWORD_SCORES: Record<TaskKind, Array<[string, number]>> = {
  research: [
    ["research", 2], ["find", 2], ["discover", 2], ["lead", 2], ["prospect", 2],
    ["search", 2], ["company", 2], ["companies", 2], ["icp", 2], ["source", 2], ["market", 2],
  ],
  inbox: [
    ["inbox", 2], ["reply", 2], ["message", 2], ["conversation", 2],
    ["gmail", 2], ["respond", 2], ["sync", 2], ["follow-up", 2], ["follow up", 2],
  ],
  campaign: [
    ["campaign", 3], ["draft", 2], ["write", 2], ["personalize", 2],
    ["launch", 2], ["outreach", 2], ["sequence", 2],
    ["strategy", 2], ["duplicate", 2], ["clone", 2], ["delete", 1],
  ],
  briefing: [
    ["brief", 2], ["what changed", 2], ["what's new", 2], ["whats new", 2],
    ["overnight", 2], ["summary", 2], ["summarize", 2], ["report", 2], ["prioritize", 2],
    ["priorities", 2], ["update", 2], ["weekly", 3],
  ],
};

export function classifyInstruction(text: string): TaskKind | "unknown" {
  const t = text.toLowerCase();
  const scores: Record<TaskKind, number> = { research: 0, inbox: 0, campaign: 0, briefing: 0 };
  (Object.keys(KEYWORD_SCORES) as TaskKind[]).forEach((kind) => {
    for (const [word, score] of KEYWORD_SCORES[kind]) {
      if (t.includes(word)) scores[kind] += score;
    }
  });
  const best = (Object.keys(scores) as TaskKind[]).reduce<TaskKind | null>(
    (acc, kind) => (acc === null || scores[kind] > scores[acc] ? kind : acc),
    null,
  );
  if (best === null || scores[best] === 0) return "unknown";
  return best;
}

/**
 * Resolve which task an instruction maps to, falling back to a page-aware
 * default when the keyword classifier cannot match.
 *
 * Discovery must never depend on keyword classification to start a search:
 * an unclassified instruction submitted there ("AI startups", "Climate tech",
 * "Healthcare SaaS", …) routes straight into the lead-search flow instead of
 * being discarded. Every other page falls through to "unknown", which the
 * caller surfaces through the clarification UI rather than silently ignoring.
 */
export function resolveTaskKind(
  instruction: string,
  page?: string | null,
): TaskKind | "unknown" {
  const kind = classifyInstruction(instruction);
  if (kind !== "unknown") return kind;
  return page === "Discovery" ? "research" : "unknown";
}

export const TASKS: Record<TaskKind, WorkspaceTask> = {
  research: { kind: "research", label: "Researching leads", workspacePath: "/discovery", workspaceLabel: "Discovery", icon: "explore" },
  campaign: { kind: "campaign", label: "Preparing campaign work", workspacePath: "/campaigns", workspaceLabel: "Campaigns", icon: "campaign" },
  inbox: { kind: "inbox", label: "Reviewing your inbox", workspacePath: "/inbox", workspaceLabel: "Inbox", icon: "inbox" },
  briefing: { kind: "briefing", label: "Preparing your briefing", workspacePath: "/mission-control", workspaceLabel: "Mission Control", icon: "auto_awesome" },
};

export const STATE_LABELS: Record<ConversationState, string> = {
  idle: "Idle",
  clarification: "Clarifying",
  working: "Working",
  completed: "Done",
};

export type QuickReplyOption = {
  id: string;
  label: string;
  hint?: string;
  instruction: string;
};

export const CLARIFICATION_PROMPT =
  "I want to make sure I work on the right thing. What should I take on next?";

export const CLARIFICATION_REPLIES: QuickReplyOption[] = [
  { id: "research", label: "Research new leads", hint: "Find prospects matching my ICP", instruction: "Find new venture leads that match my ICP" },
  { id: "briefing", label: "Refresh my briefing", hint: "What changed since yesterday", instruction: "What changed since yesterday?" },
  { id: "campaign", label: "Prepare drafts", hint: "Generate drafts for my campaign", instruction: "Prepare email drafts for my campaign" },
  { id: "inbox", label: "Check my inbox", hint: "Replies needing your decision", instruction: "Check my inbox" },
];

export function idleQuickReplies(page?: string | null): QuickReplyOption[] {
  switch (page) {
    case "Discovery":
      return [
        { id: "research-more", label: "Find more leads", hint: "Continue sourcing for this market", instruction: "Find more companies matching my ICP" },
        { id: "briefing-now", label: "What changed?", instruction: "What changed since yesterday?" },
      ];
    case "Campaign":
      return [
        { id: "drafts-now", label: "Generate drafts", hint: "For the active campaign", instruction: "Prepare email drafts for my campaign" },
        { id: "briefing-now", label: "What changed?", instruction: "What changed since yesterday?" },
      ];
    case "Inbox":
      return [
        { id: "inbox-now", label: "Summarize waiting replies", instruction: "Check my inbox" },
        { id: "briefing-now", label: "What changed?", instruction: "What changed since yesterday?" },
      ];
    default:
      return [
        { id: "briefing-now", label: "What changed?", hint: "Today's briefing", instruction: "What changed since yesterday?" },
        { id: "research-now", label: "Find new leads", hint: "Research matching my ICP", instruction: "Find new venture leads that match my ICP" },
        { id: "drafts-now", label: "Prepare drafts", hint: "For my active campaign", instruction: "Prepare email drafts for my campaign" },
        { id: "inbox-now", label: "Check my inbox", hint: "Replies needing your decision", instruction: "Check my inbox" },
      ];
  }
}

const KIND_TITLES: Record<TaskKind, string> = {
  research: "Lead Search",
  briefing: "Today's Briefing",
  campaign: "Campaign Status",
  inbox: "Inbox Review",
};

const LEAD_VERBS = ["find", "search", "research", "look for", "get me", "help me", "source", "discover"];
const STOP_WORDS = new Set([
  "the", "that", "match", "matching", "my", "new", "for", "with", "and",
  "companies", "company", "leads", "prospects", "venture", "icp", "us", "in",
]);

function titleCase(text: string): string {
  return text
    .split(" ")
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

export function taskTitle(kind: TaskKind, instruction: string): string {
  if (kind !== "research") return KIND_TITLES[kind];
  const named = titleCase(instructionSubject(instruction));
  return named ? `${named} Lead Search` : KIND_TITLES.research;
}

/**
 * Extracts the search subject ("restaurant companies") from an instruction
 * so the feed can open with natural narrative ("Looking for restaurant
 * companies…") instead of technical stage names.
 */
export function instructionSubject(instruction: string): string {
  let t = instruction.toLowerCase().trim();
  for (const verb of LEAD_VERBS) {
    if (t.startsWith(verb)) {
      t = t.slice(verb.length).trim();
      break;
    }
  }
  const words = t.replace(/[^a-z0-9 ]/g, " ").split(" ").filter(Boolean);
  const significant = words.filter((w) => !STOP_WORDS.has(w)).slice(0, 2);
  return significant.length > 0 ? significant.join(" ") : "";
}

export function researchFirstStep(instruction: string): string {
  const subject = instructionSubject(instruction);
  return subject ? `Looking for ${subject}…` : KIND_FIRST_STEPS.research;
}

export const KIND_FIRST_STEPS: Record<TaskKind, string> = {
  research: "Looking for matching companies…",
  briefing: "Reviewing overnight activity…",
  campaign: "Reviewing your campaigns…",
  inbox: "Reviewing your inbox…",
};

/**
 * Chief-of-Staff narrative stage labels for the research job engine.
 * Backend stages are translated into natural updates; technical or
 * redundant stages are skipped entirely (the feed is a narrative,
 * never a log viewer).
 */
export const RESEARCH_STAGE_LABELS: Record<string, string> = {
  "Initializing research...": "Setting up your discovery run…",
  "Understanding target market...": "Understanding your target market…",
  "Finding matching companies...": "Finding matching companies…",
  "Ranking prospects...": "Ranking the strongest matches…",
  "Preparing recommendations...": "Preparing your recommendations…",
};

export const RESEARCH_SKIPPED_STAGES = new Set([
  "Starting...",
]);

const COMPLETION_LABELS: Record<TaskKind, { primary: string; secondary: string }> = {
  research: { primary: "View Discovery", secondary: "Open Mission Control" },
  campaign: { primary: "Open Campaigns", secondary: "Review Drafts" },
  inbox: { primary: "Open Inbox", secondary: "Open Mission Control" },
  briefing: { primary: "Continue Briefing", secondary: "Open Mission Control" },
};

/**
 * Per-step campaign actions for the Copilot. Each workflow step offers the
 * exact next action on that campaign (mirrors the guided campaign lifecycle).
 */
export function campaignStepActions(
  campaignId: string,
  step: string | undefined,
): CopilotAction[] {
  const campaignPath = `/campaigns/${campaignId}`;
  switch (step) {
    case "strategy":
      return [
        { type: "navigate", label: "Generate Strategy", path: campaignPath },
        { type: "navigate", label: "Open Campaigns", path: "/campaigns" },
      ];
    case "leads":
      return [
        { type: "navigate", label: "Add Leads", path: `/discovery?campaign=${encodeURIComponent(campaignId)}` },
        { type: "navigate", label: "Open Campaign", path: campaignPath },
      ];
    case "drafts":
      return [
        { type: "navigate", label: "Generate Drafts", path: campaignPath },
        { type: "navigate", label: "Open Campaign", path: campaignPath },
      ];
    case "review":
      return [
        { type: "navigate", label: "Review Drafts", path: `/draft?campaign=${encodeURIComponent(campaignId)}` },
        { type: "navigate", label: "Open Campaign", path: campaignPath },
      ];
    case "sending":
      return [
        { type: "navigate", label: "Launch Campaign", path: campaignPath },
        { type: "navigate", label: "Open Campaign", path: campaignPath },
      ];
    default:
      return [
        { type: "navigate", label: "Open Campaign", path: campaignPath },
        { type: "navigate", label: "Open Campaigns", path: "/campaigns" },
      ];
  }
}

export function completionActions(
  task: WorkspaceTask,
  primaryPath?: string,
  extra: CopilotAction[] | null = null,
): CopilotAction[] {
  if (extra && extra.length > 0) return extra;
  const labels = COMPLETION_LABELS[task.kind];
  const actions: CopilotAction[] = [
    { type: "navigate", label: labels.primary, path: primaryPath || task.workspacePath },
  ];
  if (labels.secondary === "Open Mission Control") {
    actions.push({ type: "navigate", label: labels.secondary, path: "/mission-control" });
  } else if (task.kind === "campaign") {
    actions.push({ type: "navigate", label: labels.secondary, path: "/draft" });
  }
  return actions;
}
