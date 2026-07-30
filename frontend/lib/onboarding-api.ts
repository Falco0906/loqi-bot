const API_BASE =
  process.env.NEXT_PUBLIC_LOQI_API_BASE_URL || "http://127.0.0.1:10000";

export type OnboardingProgress = {
  lifecycle_state: string;
  current_step: string | null;
  next_route: string;
  progress_percentage: number;
  completed_steps: string[];
  remaining_steps: string[];
  total_steps: number;
  onboarding_complete: boolean;
  wizard_data: Record<string, unknown> | null;
};

export type WizardDataResponse = {
  data: Record<string, unknown>;
  onboarding_complete: boolean;
};

export type WizardSaveResponse = {
  data: Record<string, unknown>;
  onboarding_complete: boolean;
};

export type PersonalizationContext = {
  business: {
    company_name: string;
    website: string;
    description: string;
  };
  product: {
    offering: string;
    pricing_model: string;
    deal_size: string;
    sales_cycle: string;
  };
  icp: {
    target_industries: string[];
    target_company_sizes: string[];
    target_titles: string[];
    competitors: string;
  };
  geography: {
    primary_market: string;
    language: string;
    timezone: string;
  };
  goals: {
    ai_goals: string[];
    custom_goal: string;
  };
  communication: {
    tone: string;
    brand_voice: string;
  };
};

export async function getOnboardingProgress(
  userId: string,
): Promise<OnboardingProgress> {
  const res = await fetch(
    `${API_BASE}/api/v1/onboarding?user_id=${encodeURIComponent(userId)}`,
  );
  if (!res.ok) throw new Error("Failed to fetch onboarding progress");
  return res.json();
}

export async function getWizardData(
  userId: string,
): Promise<WizardDataResponse> {
  const res = await fetch(
    `${API_BASE}/api/v1/onboarding/wizard?user_id=${encodeURIComponent(userId)}`,
  );
  if (!res.ok) throw new Error("Failed to fetch wizard data");
  return res.json();
}

export async function saveWizardData(
  userId: string,
  data: Record<string, unknown>,
  completed = false,
): Promise<WizardSaveResponse> {
  const res = await fetch(
    `${API_BASE}/api/v1/onboarding/wizard?user_id=${encodeURIComponent(userId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data, completed }),
    },
  );
  if (!res.ok) throw new Error("Failed to save wizard data");
  return res.json();
}

export async function getPersonalizationContext(
  userId: string,
): Promise<PersonalizationContext> {
  const res = await fetch(
    `${API_BASE}/api/v1/onboarding/context?user_id=${encodeURIComponent(userId)}`,
  );
  if (!res.ok) throw new Error("Failed to fetch personalization context");
  return res.json();
}

export type WorkspaceCreateResponse = {
  organization_id: string;
  organization_name: string;
  organization_slug: string;
};

export async function createWorkspace(
  userId: string,
  workspaceName: string,
  slug: string,
): Promise<WorkspaceCreateResponse> {
  const res = await fetch(
    `${API_BASE}/api/v1/onboarding/workspace/create?user_id=${encodeURIComponent(userId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace_name: workspaceName, slug }),
    },
  );
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || "Failed to create workspace");
  }
  return res.json();
}