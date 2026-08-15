/**
 * Pure logic for the Settings Connected Accounts UI (PR10.8.2 live fix).
 *
 * The backend guarantees at most ONE active Gmail provider record per user
 * (communication store + provider_list dedup). These helpers keep the UI in
 * lockstep:
 *  - "Connect Gmail" is shown ONLY when no Gmail connection exists
 *  - provider statuses are surfaced accurately (auth_failed is never shown
 *    as healthy)
 *  - the display tone is derived from the backend status string
 */

export type ProviderInfo = {
  id: string;
  provider_type: string;
  status: string;
  email: string;
  last_sync?: string;
  sync_cursor?: string;
};

export function gmailProviders(providers: ProviderInfo[]): ProviderInfo[] {
  return (providers || []).filter((p) => p.provider_type === "gmail");
}

export function hasGmailProvider(providers: ProviderInfo[]): boolean {
  return gmailProviders(providers).length > 0;
}

/** The top-level "Connect Gmail" action is only offered when nothing is connected. */
export function shouldShowConnectButton(providers: ProviderInfo[]): boolean {
  return !hasGmailProvider(providers);
}

/** True when the account needs re-authentication and offers a reconnect path. */
export function isReauthRequired(status: string): boolean {
  const s = (status || "").toLowerCase();
  return s === "auth_failed" || s === "expired_token" || s === "scope_insufficient";
}

/** Tailwind tone class for a backend provider status. */
export function statusTone(status: string): string {
  switch ((status || "").toLowerCase()) {
    case "healthy":
    case "active":
    case "connected":
      return "text-success";
    case "auth_failed":
    case "expired_token":
    case "scope_insufficient":
    case "error":
      return "text-error";
    case "disconnected":
    case "offline":
      return "text-on-surface-variant/50";
    default:
      return "text-warning";
  }
}
