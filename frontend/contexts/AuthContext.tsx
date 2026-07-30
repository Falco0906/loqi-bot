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
  } catch {
    /* localStorage unavailable */
  }
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

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [state, setState] = useState<AuthState>({
    user: null,
    isAuthenticated: false,
    isLoading: true,
  });
  const initRef = useRef(false);

  const handleTokenResponse = useCallback(async (res: TokenResponse) => {
    storeTokens(res);
    try {
      const me = await fetchMe(res.user_id);
      setState({
        user: me,
        isAuthenticated: true,
        isLoading: false,
      });
    } catch {
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
      handleTokenResponse(res);
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
      await handleTokenResponse(res);
      
      // Check onboarding status before redirecting
      try {
        const userId = res.user_id;
        const progress = await getOnboardingProgress(userId);
        if (progress.onboarding_complete) {
          router.push("/mission-control");
        } else {
          router.push("/first-meeting");
        }
      } catch {
        // If onboarding check fails, default to first meeting
        router.push("/first-meeting");
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
      await handleTokenResponse(tokenRes);
      
      // Check onboarding status before redirecting
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