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
  let storedAccessToken = "";
  try { storedAccessToken = localStorage.getItem("loqi_access_token") || ""; } catch { /* SSR/storage unavailable */ }
  const response = await fetch(
    `${API_BASE}/api/v1/strategic-intelligence/generate`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(storedAccessToken ? { Authorization: `Bearer ${storedAccessToken}` } : {}),
      },
      body: JSON.stringify(data),
    },
  );

  if (!response.ok) {
    // The backend intentionally redacts all 5xx bodies. Status remains
    // meaningful without exposing provider responses or internal exceptions.
    if (response.status === 502) {
      throw new Error("The AI did not return a usable profile. Your answers are saved; retry or continue without a profile.");
    }
    if (response.status === 503) {
      throw new Error("The AI profile service is unavailable. Your answers are saved; retry or continue without a profile.");
    }
    if (response.status === 504) {
      throw new Error("Profile generation timed out. Your answers are saved; retry or continue without a profile.");
    }
    if (response.status >= 500) {
      throw new Error("Profile generation failed. Your answers are saved; you can continue without a profile.");
    }
    const body: unknown = await response.json().catch(() => null);
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : null;
    throw new Error(typeof detail === "string" ? detail : "Profile generation failed. Your answers are saved; you can continue without a profile.");
  }

  return response.json();
}

export async function getStrategicProfile(
  userId: string,
): Promise<{ profile: StrategicProfile | null; generated_at: string | null }> {
  let storedAccessToken = "";
  try { storedAccessToken = localStorage.getItem("loqi_access_token") || ""; } catch { /* SSR/storage unavailable */ }
  const response = await fetch(
    `${API_BASE}/api/v1/strategic-intelligence/profile/${encodeURIComponent(userId)}`,
    {
      headers: {
        "Content-Type": "application/json",
        ...(storedAccessToken ? { Authorization: `Bearer ${storedAccessToken}` } : {}),
      },
    },
  );

  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || "Failed to get strategic profile");
  }

  return response.json();
}
