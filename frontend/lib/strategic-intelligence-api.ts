// Frontend API client for strategic intelligence service.

const API_BASE =
  process.env.NEXT_PUBLIC_LOQI_API_BASE_URL || "http://127.0.0.1:10000";

export type StrategicProfile = {
  COMPANY_SUMMARY: string;
  INDUSTRY: string;
  BUSINESS_MODEL: string;
  PRODUCT: string;
  ICP: string;
  BUYER_PERSONAS: Array<{
    name: string;
    title: string;
    motivation: string;
    objections: string;
  }>;
  DIFFERENTIATION: string;
  MARKET_POSITION: string;
  COMPETITIVE_LANDSCAPE: string;
  PRIMARY_OBJECTIVE: string;
  CURRENT_CONSTRAINTS: string;
  RISKS: string[];
  GROWTH_OPPORTUNITIES: string[];
  MESSAGING: string;
  CONFIDENCE_LEVELS: Record<string, string>;
  KNOWN_UNKNOWNS: string[];
};

export type GenerateProfileRequest = {
  company_description: string;
  ideal_customer: string;
  differentiation: string;
  annual_goal: string;
  biggest_obstacle: string;
  website?: string | null;
  user_id?: string | null;
};

export type GenerateProfileResponse = {
  profile: StrategicProfile;
  generated_at: string;
};

export async function generateStrategicProfile(
  data: GenerateProfileRequest,
): Promise<GenerateProfileResponse> {
  const response = await fetch(
    `${API_BASE}/api/v1/strategic-intelligence/generate`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    },
  );

  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || "Failed to generate strategic profile");
  }

  return response.json();
}

export async function getStrategicProfile(
  userId: string,
): Promise<{ profile: StrategicProfile | null; generated_at: string | null }> {
  const response = await fetch(
    `${API_BASE}/api/v1/strategic-intelligence/profile/${encodeURIComponent(userId)}`,
    {
      headers: {
        "Content-Type": "application/json",
      },
    },
  );

  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || "Failed to get strategic profile");
  }

  return response.json();
}
