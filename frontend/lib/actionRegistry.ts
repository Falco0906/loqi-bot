"use client";

export type ActionType =
  | "navigate"
  | "select_all"
  | "clear_selection"
  | "compare"
  | "plan_campaign"
  | "generate_drafts"
  | "approve"
  | "approve_all"
  | "refine"
  | "search"
  | "save_campaign"
  | "export_csv"
  | "launch_campaign"
  | "view_drafts"
  | "open_campaign";

export type CopilotAction = {
  type: "navigate" | "action";
  label: string;
  path?: string;
  action?: ActionType;
  payload?: Record<string, unknown>;
};

export type ActionDefinition = {
  id: ActionType;
  label: string;
  description: string;
  page?: string;
};

export type ActionHandler = (
  params?: Record<string, unknown>,
) => void | Promise<void>;

export const ACTION_REGISTRY: Record<ActionType, ActionDefinition> = {
  navigate: {
    id: "navigate",
    label: "Navigate",
    description: "Go to a page",
  },
  select_all: {
    id: "select_all",
    label: "Select All",
    description: "Select all visible leads",
    page: "Discovery",
  },
  clear_selection: {
    id: "clear_selection",
    label: "Clear Selection",
    description: "Clear current selection",
    page: "Discovery",
  },
  compare: {
    id: "compare",
    label: "Compare",
    description: "Compare selected leads",
    page: "Discovery",
  },
  plan_campaign: {
    id: "plan_campaign",
    label: "Plan Campaign",
    description: "Create a campaign from selected leads",
    page: "Discovery",
  },
  generate_drafts: {
    id: "generate_drafts",
    label: "Generate Drafts",
    description: "Generate email drafts for this campaign",
    page: "Campaign",
  },
  approve: {
    id: "approve",
    label: "Approve",
    description: "Approve the current draft",
    page: "Draft Review",
  },
  approve_all: {
    id: "approve_all",
    label: "Approve All",
    description: "Approve all pending drafts",
    page: "Draft Review",
  },
  refine: {
    id: "refine",
    label: "Refine",
    description: "Refine the current draft",
    page: "Draft Review",
  },
  search: {
    id: "search",
    label: "Search",
    description: "Search for leads",
    page: "Discovery",
  },
  save_campaign: {
    id: "save_campaign",
    label: "Save Campaign",
    description: "Save the current campaign",
    page: "Discovery",
  },
  export_csv: {
    id: "export_csv",
    label: "Export CSV",
    description: "Export leads to CSV",
    page: "Discovery",
  },
  launch_campaign: {
    id: "launch_campaign",
    label: "Launch Campaign",
    description: "Launch a campaign",
  },
  view_drafts: {
    id: "view_drafts",
    label: "View Drafts",
    description: "Go to draft review",
  },
  open_campaign: {
    id: "open_campaign",
    label: "Open Campaign",
    description: "Open a specific campaign",
  },
};
