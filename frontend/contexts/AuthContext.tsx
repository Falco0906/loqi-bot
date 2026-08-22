"use client";

import {
  createContext,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import {
  login as apiLogin,
  logout as apiLogout,
  refreshToken as apiRefresh,
  beginRegistration,
  completeRegistration as apiCompleteRegistration,
  getRegistrationStatus,
  fetchMe,
  getGoogleOAuthUrl,
  oauthCallback,
  type TokenResponse,
  type MeResponse,
  type OAuthCallbackResponse,
} from "../lib/auth-api";
import { getOnboardingProgress } from "../lib/onboarding-api";
import { createSession } from "../lib/api";

const STORAGE_KEYS = {
  ACCESS_TOKEN: "loqi_access_token",
  REFRESH_TOKEN: "loqi_refresh_token",
  USER_ID: "loqi_user_id",
  ORG_ID: "loqi_org_id",
  PENDING_REGISTRATION: "loqi_pending_registration",
} as const;

type PendingRegistration = {
  registrationSessionId: string;
  email: string;
  displayName: string;
  password: string;
  organizationName: string;
};

type User = MeResponse | { id: string; orgId: string };

type AuthState = {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
};

type AuthActions = {
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string) => Promise<string>;
  completeRegistration: (
    sessionId: string,
    displayName: string,
    password: string,
    orgName: string,
  ) => Promise<void>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
  refreshUser: () => Promise<void>;
  storePendingRegistration: (data: PendingRegistration) => void;
  getPendingRegistration: () => PendingRegistration | null;
  clearPendingRegistration: () => void;
  initiateGoogleLogin: () => Promise<void>;
  handleOAuthCallback: (code: string, state: string) => Promise<void>;
  updateUser: (updates: Partial<MeResponse>) => void;
};

const AuthContext = createContext<AuthState & AuthActions | null>(null);

function storeTokens(res: TokenResponse) {
  try {
    localStorage.setItem(STORAGE_KEYS.ACCESS_TOKEN, res.access_token);
    localStorage.setItem(STORAGE_KEYS.REFRESH_TOKEN, res.refresh_token);
    localStorage.setItem(STORAGE_KEYS.USER_ID, res.user_id);
    localStorage.setItem(STORAGE_KEYS.ORG_ID, res.org_id);
  } catch {
    /* localStorage unavailable */
  }
}

function clearStoredTokens() {
  try {
    for (const key of Object.values(STORAGE_KEYS)) {
      localStorage.removeItem(key);
    }
    // PR-P1.5: the web-session token belongs to the logged-in user — drop it
    // on logout/credential reset so the next user gets a fresh session.
    localStorage.removeItem("loqi_active_session_token");
  } catch {
    /* localStorage unavailable */
  }
  // PR-3C: purge every client-cached API payload — cached data must never
  // survive an identity boundary (logout, re-auth, registration switch).
  import("../lib/client-cache").then(({ clearClientCache }) => clearClientCache());
  import("../lib/nav-state").then(({ clearNavState }) => clearNavState());
  try { sessionStorage.removeItem("loqi_copilot_conversation"); } catch { /* noop */ }
}

function readStoredUser(): User | null {
  try {
    const userId = localStorage.getItem(STORAGE_KEYS.USER_ID);
    const orgId = localStorage.getItem(STORAGE_KEYS.ORG_ID);
    if (userId) {
      return { id: userId, orgId: orgId || "" };
    }
  } catch {
    /* localStorage unavailable */
  }
  return null;
}

function readStoredRefreshToken(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEYS.REFRESH_TOKEN);
  } catch {
    return null;
  }
}

const ACTIVE_WEB_SESSION_KEY = "loqi_active_session_token";

async function establishWebSession(displayName: string): Promise<void> {
  // PR-P1.5: reuse an existing active web-session token instead of creating
  // a brand-new backend session on every hard load / login. Web sessions are
  // durable server-side, so a stored token stays resolvable across reloads.
  // Cross-user leakage is prevented by dropping the token on logout and
  // whenever the authenticated user id changes (see handleTokenResponse).
  try {
    const existing = localStorage.getItem(ACTIVE_WEB_SESSION_KEY);
    if (existing) return;
  } catch {
    /* localStorage unavailable */
  }
  try {
    const session = await createSession(displayName || "Loqi Operator");
    if (session.ok && session.session_token) {
      localStorage.setItem(ACTIVE_WEB_SESSION_KEY, session.session_token);
    }
  } catch {
    // Authentication remains valid if workspace-session bootstrap is
    // temporarily unavailable; dashboard requests can retry it later.
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [state, setState] = useState<AuthState>({
    user: null,
    isAuthenticated: false,
    isLoading: true,
  });
  const initRef = useRef(false);

  const handleTokenResponse = useCallback(async (res: TokenResponse): Promise<MeResponse | null> => {
    // PR-P1.5: if the authenticated user changed, drop the previous user's
    // web-session token so establishWebSession mints a fresh one for them.
    try {
      const prevUserId = localStorage.getItem(STORAGE_KEYS.USER_ID);
      if (prevUserId && prevUserId !== res.user_id) {
        localStorage.removeItem(ACTIVE_WEB_SESSION_KEY);
      }
    } catch {
      /* localStorage unavailable */
    }
    storeTokens(res);
    try {
      const me = await fetchMe(res.user_id);
      // PR-P1.5 (race fix): keep isLoading true until the web session is
      // established. Children gated on isAuthenticated/isLoading must not
      // render — and read loqi_active_session_token — before it exists.
      await establishWebSession(me.display_name);
      setState({
        user: me,
        isAuthenticated: true,
        isLoading: false,
      });
      return me;
    } catch {
      await establishWebSession("");
      setState({
        user: {
          id: res.user_id,
          email: "",
          display_name: "",
          avatar_url: "",
          onboarding_complete: false,
          organization: null,
        },
        isAuthenticated: true,
        isLoading: false,
      });
      return null;
    }
  }, []);

  const refreshSession = useCallback(async () => {
    const refresh = readStoredRefreshToken();
    if (!refresh) {
      setState({ user: null, isAuthenticated: false, isLoading: false });
      return;
    }
    try {
      const res = await apiRefresh(refresh);
      // PR-P1.5: await so the init effect truly waits for session setup.
      await handleTokenResponse(res);
    } catch {
      clearStoredTokens();
      setState({ user: null, isAuthenticated: false, isLoading: false });
    }
  }, [handleTokenResponse]);

  const refreshUser = useCallback(async () => {
    const userId = localStorage.getItem(STORAGE_KEYS.USER_ID);
    if (!userId) return;
    const me = await fetchMe(userId);
    setState((s) => ({ ...s, user: me }));
  }, []);

  const tryAutoComplete = useCallback(async () => {
    let pending: PendingRegistration | null = null;
    try {
      const raw = localStorage.getItem(STORAGE_KEYS.PENDING_REGISTRATION);
      if (raw) pending = JSON.parse(raw);
    } catch {
      /* ignore */
    }
    if (!pending) return false;

    try {
      const status = await getRegistrationStatus(
        pending.registrationSessionId,
      );
      if (status.status === "verified") {
        const res = await apiCompleteRegistration(
          pending.registrationSessionId,
          pending.displayName,
          pending.password,
          pending.organizationName,
        );
        clearStoredTokens();
        await handleTokenResponse(res);
        // After registration, go to first meeting
        router.push("/first-meeting");
        return true;
      }
    } catch {
      return false;
    }
    return false;
  }, [handleTokenResponse]);

  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;

    (async () => {
      const user = readStoredUser();
      if (user) {
        try {
          await refreshSession();
          return;
        } catch {
          /* fall through to auto-complete */
        }
      }

      const completed = await tryAutoComplete();
      if (!completed) {
        setState((s) => ({ ...s, isLoading: false }));
      }
    })();
  }, [refreshSession, tryAutoComplete]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await apiLogin(email, password);
      const me = await handleTokenResponse(res);
      // The authenticated profile is the primary source of truth. The
      // onboarding endpoint is only needed for older accounts that do not
      // expose the completion flag yet.
      if (me?.onboarding_complete) {
        router.push("/mission-control");
        return;
      }
      try {
        const userId = res.user_id;
        const progress = await getOnboardingProgress(userId);
        if (progress.onboarding_complete) {
          router.push("/mission-control");
        } else {
          router.push("/first-meeting");
        }
      } catch {
        // Do not turn a status transport failure into a false onboarding
        // reset. If profile loading succeeded, it was already handled above.
        router.push(me ? "/mission-control" : "/first-meeting");
      }
    },
    [handleTokenResponse, router],
  );

  const signup = useCallback(async (email: string) => {
    const res = await beginRegistration(email);
    return res.registration_session_id;
  }, []);

  const completeRegistrationAction = useCallback(
    async (
      sessionId: string,
      displayName: string,
      password: string,
      orgName: string,
    ) => {
      const res = await apiCompleteRegistration(
        sessionId,
        displayName,
        password,
        orgName,
      );
      clearStoredTokens();
      await handleTokenResponse(res);
      
      // After registration, go to first meeting
      router.push("/first-meeting");
    },
    [handleTokenResponse, router],
  );

  const logout = useCallback(async () => {
    const refresh = readStoredRefreshToken();
    if (refresh) {
      try {
        await apiLogout(refresh);
      } catch {
        /* proceed with local logout even if server call fails */
      }
    }
    clearStoredTokens();
    setState({ user: null, isAuthenticated: false, isLoading: false });
    router.push("/login");
  }, [router]);

  const storePendingRegistration = useCallback(
    (data: PendingRegistration) => {
      try {
        localStorage.setItem(
          STORAGE_KEYS.PENDING_REGISTRATION,
          JSON.stringify(data),
        );
      } catch {
        /* ignore */
      }
    },
    [],
  );

  const getPendingRegistration = useCallback((): PendingRegistration | null => {
    try {
      const raw = localStorage.getItem(STORAGE_KEYS.PENDING_REGISTRATION);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }, []);

  const clearPendingRegistration = useCallback(() => {
    try {
      localStorage.removeItem(STORAGE_KEYS.PENDING_REGISTRATION);
    } catch {
      /* ignore */
    }
  }, []);

  const initiateGoogleLogin = useCallback(async () => {
    const { authorize_url } = await getGoogleOAuthUrl();
    window.location.href = authorize_url;
  }, []);

  const updateUser = useCallback((updates: Partial<MeResponse>) => {
    setState((s) => {
      if (!s.user) return s;
      return { ...s, user: { ...s.user, ...updates } };
    });
  }, []);

  const handleOAuthCallback = useCallback(
    async (code: string, state: string) => {
      const res = await oauthCallback(code, state);
      const tokenRes: TokenResponse = {
        access_token: res.access_token,
        refresh_token: res.refresh_token,
        session_id: res.session_id,
        user_id: res.user_id,
        org_id: res.org_id,
        expires_at: res.expires_at,
      };
      const me = await handleTokenResponse(tokenRes);

      // Google OAuth already resolves whether this is a new identity. An
      // existing Google account must go straight to the application even if
      // the separate onboarding progress request is unavailable.
      if (!res.is_new_user || me?.onboarding_complete) {
        router.push("/mission-control");
        return;
      }
      try {
        const progress = await getOnboardingProgress(res.user_id);
        if (progress.onboarding_complete) {
          router.push("/mission-control");
        } else {
          router.push("/first-meeting");
        }
      } catch {
        router.push("/first-meeting");
      }
    },
    [handleTokenResponse, router],
  );

  return (
    <AuthContext.Provider
      value={{
        ...state,
        login,
        signup,
        completeRegistration: completeRegistrationAction,
        logout,
        refreshSession,
        refreshUser,
        storePendingRegistration,
        getPendingRegistration,
        clearPendingRegistration,
        initiateGoogleLogin,
        handleOAuthCallback,
        updateUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export { AuthContext, STORAGE_KEYS };
export type { PendingRegistration };
