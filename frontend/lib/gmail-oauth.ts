/**
 * Gmail OAuth popup helper (PR10.9 OAuth UX regression fix).
 *
 * Root cause of the production regression: the connect handler awaited the
 * auth-URL fetch BEFORE calling window.open, so browsers treated the popup as
 * not-user-gesture-initiated and blocked it; the old code then fell back to
 * window.location.href, navigating the main Loqi tab to the callback.
 *
 * This helper opens the (blank) popup SYNCHRONOUSLY within the click gesture
 * so it is not blocked, fetches the auth URL afterwards, and navigates the
 * popup to it. If the popup is genuinely blocked it reports "blocked" — the
 * caller must NOT navigate the main tab away.
 *
 * postMessage: the opener listener must validate the sender origin with
 * isTrustedGmailOAuthMessage (strict, never "*").
 */

export type GmailAuthPopupResult =
  | { status: "opened" }
  | { status: "blocked" }
  | { status: "error" };

const DEFAULT_API_BASE =
  (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_LOQI_API_BASE_URL) ||
  "http://127.0.0.1:10000";

/** The origin the OAuth callback popup runs on (the API base origin). */
export function apiOrigin(base: string = DEFAULT_API_BASE): string {
  try {
    return new URL(base).origin;
  } catch {
    return base;
  }
}

/**
 * Strict postMessage sender validation: accept messages only from the API
 * origin (the callback popup's origin). Never matches "*".
 */
export function isTrustedGmailOAuthMessage(
  event: { origin?: string },
  expectedOrigin: string = apiOrigin(),
): boolean {
  return !!expectedOrigin && event.origin === expectedOrigin;
}

function defaultOpen(url: string, name: string, features: string): Window | null {
  if (typeof window === "undefined") return null;
  return window.open(url, name, features);
}

function defaultClose(popup: Window): void {
  try {
    popup.close();
  } catch {
    /* ignore */
  }
}

/**
 * Open the Gmail OAuth flow in a separate popup.
 *
 * Opens a blank popup synchronously (user gesture), then fetches the auth URL
 * and navigates the popup to it. Returns:
 * - "opened": popup is showing the Google consent screen
 * - "blocked": popup could not be opened — caller should surface a hint and
 *   keep the app tab open (never navigate the main tab to the OAuth URL)
 * - "error": the auth URL could not be obtained (popup is closed)
 */
export async function openGmailAuthPopup(
  fetchUrl: () => Promise<{ ok: boolean; url?: string }>,
  open: (url: string, name: string, features: string) => Window | null = defaultOpen,
  closeWindow: (popup: Window) => void = defaultClose,
): Promise<GmailAuthPopupResult> {
  const popup = open("", "gmail-oauth", "width=600,height=700");
  try {
    const res = await fetchUrl();
    if (!res || !res.ok || !res.url) {
      if (popup) closeWindow(popup);
      return { status: "error" };
    }
    if (popup) {
      popup.location.href = res.url;
      return { status: "opened" };
    }
    return { status: "blocked" };
  } catch {
    if (popup) closeWindow(popup);
    return { status: "error" };
  }
}
