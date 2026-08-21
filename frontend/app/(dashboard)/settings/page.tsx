"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Icon from "../../../components/shared/Icon";
import ThemeToggle from "../../../components/shared/ThemeToggle";
import { getGmailAuthUrl, listProviders, disconnectProvider, getProviderHealth } from "../../../lib/api";
import {
  hasGmailProvider,
  isReauthRequired,
  shouldShowConnectButton,
  statusTone,
  type ProviderInfo,
} from "../../../lib/gmail-settings";
import { isTrustedGmailOAuthMessage, openGmailAuthPopup } from "../../../lib/gmail-oauth";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";

export default function SettingsPage() {
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState("");
  // PR-2A §10: a failed /providers request must NOT render as "No Gmail
  // accounts connected" — that misleads users into reconnecting.
  const [loadError, setLoadError] = useState("");
  const [healthMap, setHealthMap] = useState<Record<string, { status: string; last_sync: string }>>({});

  // PR-2A §7: guards so neither the provider list nor the per-provider
  // health checks can overlap themselves or outlive this component.
  const fetchInFlight = useRef(false);
  const healthInFlight = useRef<Set<string>>(new Set());
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    const token = (() => {
      try { return localStorage.getItem(ACTIVE_SESSION_KEY); }
      catch { return null; }
    })();
    setSessionToken(token);
  }, []);

  const fetchProviders = useCallback(async () => {
    if (!sessionToken || fetchInFlight.current) return;
    fetchInFlight.current = true;
    setLoading(true);
    setLoadError("");
    try {
      const res = await listProviders(sessionToken);
      if (!mounted.current) return;
      if (res.ok) {
        setProviders(res.providers || []);
        setHealthMap({});
        // PR-2A §9: one health request per provider, deduped, fire-and-forget.
        // Health failures never break the provider list itself.
        for (const p of res.providers || []) {
          void fetchHealth(p.id);
        }
      } else {
        setLoadError("Unable to load connected accounts. Please try again.");
      }
    } catch {
      if (mounted.current) {
        setLoadError("Unable to load connected accounts. Please try again.");
      }
    } finally {
      fetchInFlight.current = false;
      if (mounted.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionToken]);

  const fetchHealth = useCallback(async (providerId: string) => {
    if (!sessionToken || !providerId) return;
    // Dedupe: skip if this provider's health check is already running.
    if (healthInFlight.current.has(providerId)) return;
    healthInFlight.current.add(providerId);
    try {
      const h = await getProviderHealth(sessionToken, providerId);
      if (!mounted.current || !h.ok) return;
      setHealthMap(prev => ({ ...prev, [providerId]: { status: h.status, last_sync: h.last_sync } }));
    } catch {
      /* PR-2A §10 case D: leave "health unknown" rather than failing the account */
    } finally {
      healthInFlight.current.delete(providerId);
    }
  }, [sessionToken]);

  useEffect(() => {
    if (sessionToken) fetchProviders();
  }, [sessionToken, fetchProviders]);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      // Strict origin validation: only accept messages from the API origin
      // (the Gmail OAuth callback popup). Never trust a message from an
      // arbitrary origin.
      if (!isTrustedGmailOAuthMessage(event)) return;
      if (event.data?.type !== "gmail-oauth") return;
      // PR-2A §7: the callback payload decides what the UI does. A failed
      // OAuth must surface an error — never trigger a refresh as if the
      // account connected, and never claim success.
      const payload = event.data.payload as { ok?: boolean; error?: string } | undefined;
      if (!payload?.ok) {
        setConnecting(false);
        setConnectError(
          payload?.error
            ? `Gmail connection failed: ${payload.error}`
            : "Gmail connection failed. Please try again."
        );
        return;
      }
      setConnecting(false);
      setConnectError("");
      // Durable persistence completed before this message was sent — exactly
      // ONE provider refresh is needed (no polling).
      fetchProviders();
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [fetchProviders]);

  const handleConnect = async () => {
    if (!sessionToken) return;
    setConnecting(true);
    setConnectError("");
    // PR10.9: open the popup synchronously (within the click gesture) so it
    // is not blocked, then navigate it to the auth URL. Never replace the
    // current Loqi tab with the OAuth callback.
    const result = await openGmailAuthPopup(() => getGmailAuthUrl(sessionToken));
    if (result.status === "blocked") {
      setConnecting(false);
      setConnectError("Popup blocked — please allow popups for this site and try again.");
    } else if (result.status === "error") {
      setConnecting(false);
      setConnectError("Could not start Gmail connection. Please try again.");
    }
    // "opened" keeps the button disabled until the popup reports back via
    // postMessage (the message handler above re-fetches the accounts).
  };

  const handleDisconnect = async (providerId: string) => {
    if (!sessionToken) return;
    try {
      await disconnectProvider(sessionToken, providerId);
      setProviders(prev => prev.filter(p => p.id !== providerId));
      setHealthMap(prev => {
        const next = { ...prev };
        delete next[providerId];
        return next;
      });
    } catch {
      // PR-2A §10: a disconnect failure must not silently pretend success.
      setConnectError("Could not disconnect this account. Please try again.");
      fetchProviders();
    }
  };

  const showConnect = shouldShowConnectButton(providers);

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      {/* Appearance */}
      <section className="mb-10">
        <h2 className="text-lg font-semibold text-on-surface mb-4">Appearance</h2>
        <div className="flex items-center justify-between rounded-xl border border-outline-variant/10 bg-charcoal/50 px-5 py-4">
          <div>
            <span className="text-sm text-on-surface">Theme</span>
            <p className="text-xs text-on-surface-variant/60 mt-0.5">Switch between light and dark mode</p>
          </div>
          <ThemeToggle />
        </div>
      </section>

      {/* Connected Accounts */}
      <section className="mb-10">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-on-surface">Connected Accounts</h2>
          {showConnect && (
            <button
              onClick={handleConnect}
              disabled={connecting}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-on-primary hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {connecting ? (
                <span className="w-4 h-4 border-2 border-on-primary border-t-transparent rounded-full animate-spin" />
              ) : (
                <Icon name="add_circle" className="text-base" />
              )}
              {connecting ? "Connecting..." : "Connect Gmail"}
            </button>
          )}
        </div>

        {connectError && (
          <p className="mb-3 text-sm text-error" role="alert">{connectError}</p>
        )}

        {loading ? (
          <div className="flex items-center gap-3 rounded-xl border border-outline-variant/10 bg-charcoal/50 px-5 py-6">
            <span className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            <span className="text-sm text-on-surface-variant/60">Loading accounts...</span>
          </div>
        ) : loadError ? (
          /* PR-2A §10 case B: request failed — never render as "no accounts" */
          <div className="rounded-xl border border-error/30 bg-error/5 px-5 py-8 text-center">
            <Icon name="warning" className="text-3xl text-error mb-2" />
            <p className="text-sm text-on-surface">{loadError}</p>
            <button
              onClick={() => fetchProviders()}
              className="mt-3 rounded-lg border border-primary/40 px-4 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 transition-colors"
            >
              Retry
            </button>
          </div>
        ) : providers.length === 0 ? (
          /* PR-2A §10 case A: genuinely zero providers */
          <div className="rounded-xl border border-outline-variant/10 bg-charcoal/50 px-5 py-8 text-center">
            <Icon name="mail" className="text-3xl text-on-surface-variant/30 mb-2" />
            <p className="text-sm text-on-surface-variant/60">No Gmail accounts connected</p>
            <p className="text-xs text-on-surface-variant/40 mt-1">Connect a Gmail account to send and receive emails.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {providers.map((p) => {
              const health = healthMap[p.id];
              const reauth = isReauthRequired(p.status) || (health ? isReauthRequired(health.status) : false);
              return (
                <div key={p.id} className="flex items-center justify-between rounded-xl border border-outline-variant/10 bg-charcoal/50 px-5 py-4">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-container/20 shrink-0">
                      <Icon name="mail" className="text-lg text-primary" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-on-surface truncate">{p.email || "Gmail"}</span>
                        <span className={`text-xs font-medium ${statusTone(p.status)}`}>{p.status}</span>
                      </div>
                      <div className="flex items-center gap-3 mt-0.5">
                        {health ? (
                          <>
                            <span className={`text-xs ${statusTone(health.status)}`}>{health.status}</span>
                            {health.last_sync && (
                              <span className="text-xs text-on-surface-variant/50">Last sync: {new Date(health.last_sync).toLocaleString()}</span>
                            )}
                          </>
                        ) : (
                          <span className="text-xs text-on-surface-variant/50">Health unknown</span>
                        )}
                      </div>
                      {reauth && (
                        <p className="text-xs text-error mt-1">
                          Gmail re-authentication is required. Reconnect to resume syncing.
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={handleConnect}
                      disabled={connecting}
                      className="rounded-lg px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
                    >
                      {reauth ? "Reconnect Gmail" : "Reconnect"}
                    </button>
                    <button
                      onClick={() => handleDisconnect(p.id)}
                      className="rounded-lg px-3 py-1.5 text-xs font-medium text-error hover:bg-error/10 transition-colors"
                    >
                      Disconnect
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
