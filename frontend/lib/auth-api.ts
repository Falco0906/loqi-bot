const API_BASE =
  process.env.NEXT_PUBLIC_LOQI_API_BASE_URL || "http://127.0.0.1:10000";

export async function authFetch<T>(
  url: string,
  options: RequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 10000);

  try {
    const response = await fetch(url, {
      ...options,
      signal: options.signal || controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const message =
        body?.detail || body?.message || `Request failed (${response.status})`;
      throw new AuthApiError(message, response.status, body?.code);
    }

    return (await response.json()) as T;
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof AuthApiError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new AuthApiError("Request timed out", 0, "TIMEOUT");
    }
    throw new AuthApiError(
      err instanceof Error ? err.message : "Network error",
      0,
      "NETWORK",
    );
  }
}

export class AuthApiError extends Error {
  status: number;
  code: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "AuthApiError";
    this.status = status;
    this.code = code || "UNKNOWN";
  }
}

export type SignupResponse = {
  registration_session_id: string;
  expires_at: string;
};

export type StatusResponse = {
  registration_session_id: string;
  email: string;
  status: "pending" | "verified" | "completed" | "expired";
};

export type VerifyResponse = {
  ok: boolean;
  message: string;
};

export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  session_id: string;
  user_id: string;
  org_id: string;
  expires_at: string;
};

export type OAuthCallbackResponse = {
  access_token: string;
  refresh_token: string;
  session_id: string;
  user_id: string;
  org_id: string;
  expires_at: string;
  is_new_user: boolean;
};

export type OAuthUrlResponse = {
  authorize_url: string;
};

export type MeOrganizationResponse = {
  id: string;
  name: string;
  slug: string;
  role: string;
};

export type MeResponse = {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string;
  onboarding_complete: boolean;
  organization: MeOrganizationResponse | null;
};

export function beginRegistration(email: string): Promise<SignupResponse> {
  return authFetch<SignupResponse>(`${API_BASE}/api/v1/auth/signup/email`, {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function getRegistrationStatus(
  sessionId: string,
): Promise<StatusResponse> {
  return authFetch<StatusResponse>(
    `${API_BASE}/api/v1/auth/signup/email/status/${encodeURIComponent(sessionId)}`,
  );
}

export function verifyEmail(token: string): Promise<VerifyResponse> {
  return authFetch<VerifyResponse>(
    `${API_BASE}/api/v1/auth/signup/email/verify`,
    {
      method: "POST",
      body: JSON.stringify({ token }),
    },
  );
}

export function completeRegistration(
  registrationSessionId: string,
  displayName: string,
  password: string,
  organizationName: string,
): Promise<TokenResponse> {
  return authFetch<TokenResponse>(
    `${API_BASE}/api/v1/auth/signup/email/complete`,
    {
      method: "POST",
      body: JSON.stringify({
        registration_session_id: registrationSessionId,
        display_name: displayName,
        password,
        organization_name: organizationName,
      }),
    },
  );
}

export function login(
  email: string,
  password: string,
): Promise<TokenResponse> {
  return authFetch<TokenResponse>(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function refreshToken(
  refreshToken: string,
): Promise<TokenResponse> {
  return authFetch<TokenResponse>(`${API_BASE}/api/v1/auth/refresh`, {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

export function logout(
  refreshToken: string,
): Promise<{ ok: boolean; message: string }> {
  return authFetch(`${API_BASE}/api/v1/auth/logout`, {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

export function getGoogleOAuthUrl(
  redirectUri?: string,
): Promise<OAuthUrlResponse> {
  const params = redirectUri
    ? `?redirect_uri=${encodeURIComponent(redirectUri)}`
    : "";
  return authFetch<OAuthUrlResponse>(
    `${API_BASE}/api/v1/auth/oauth/google${params}`,
  );
}

export function oauthCallback(
  code: string,
  state: string,
): Promise<OAuthCallbackResponse> {
  return authFetch<OAuthCallbackResponse>(
    `${API_BASE}/api/v1/auth/oauth/google/callback?code=${encodeURIComponent(
      code,
    )}&state=${encodeURIComponent(state)}`,
  );
}

export function fetchMe(userId: string): Promise<MeResponse> {
  return authFetch<MeResponse>(
    `${API_BASE}/api/v1/auth/me?user_id=${encodeURIComponent(userId)}`,
  );
}