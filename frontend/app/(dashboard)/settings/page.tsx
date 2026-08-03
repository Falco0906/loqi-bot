"use client";

import { useState, useEffect, useCallback } from "react";
import Icon from "../../../components/shared/Icon";
import ThemeToggle from "../../../components/shared/ThemeToggle";
import { getGmailAuthUrl, listProviders, disconnectProvider, getProviderHealth } from "../../../lib/api";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";

type Provider = {
  id: string;
  provider_type: string;
  status: string;
  email: string;
  last_sync: string;
};

export default function SettingsPage() {
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [healthMap, setHealthMap] = useState<Record<string, { status: string; last_sync: string }>>({});

  useEffect(() => {
    const token = (() => {
      try { return localStorage.getItem(ACTIVE_SESSION_KEY); }
      catch { return null; }
    })();
    setSessionToken(token);
  }, []);

  const fetchProviders = useCallback(async () => {
    if (!sessionToken) return;
    setLoading(true);
    try {
      const res = await listProviders(sessionToken);
      if (res.ok) {
        const gmailProviders = (res.providers || []).filter(p => p.provider_type === "gmail");
        setProviders(gmailProviders);
        gmailProviders.forEach(async (p) => {
          try {
            const h = await getProviderHealth(sessionToken, p.id);
            if (h.ok) {
              setHealthMap(prev => ({ ...prev, [p.id]: { status: h.status, last_sync: h.last_sync } }));
            }
          } catch {}
        });
      }
    } catch {}
    setLoading(false);
  }, [sessionToken]);

  useEffect(() => {
    if (sessionToken) fetchProviders();
  }, [sessionToken, fetchProviders]);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (event.data?.type === "gmail-oauth") {
        setConnecting(false);
        fetchProviders();
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [fetchProviders]);

  const handleConnect = async () => {
    if (!sessionToken) return;
    setConnecting(true);
    try {
      const res = await getGmailAuthUrl(sessionToken);
      if (res.ok && res.url) {
        const popup = window.open(res.url, "gmail-oauth", "width=600,height=700");
        if (!popup) {
          window.location.href = res.url;
        }
      } else {
        setConnecting(false);
      }
    } catch {
      setConnecting(false);
    }
  };

  const handleDisconnect = async (providerId: string) => {
    if (!sessionToken) return;
    try {
      await disconnectProvider(sessionToken, providerId);
      setProviders(prev => prev.filter(p => p.id !== providerId));
    } catch {}
  };

  const statusColor = (status: string) => {
    switch (status) {
      case "connected": return "text-success";
      case "error": return "text-error";
      case "disconnected": return "text-on-surface-variant/50";
      default: return "text-warning";
    }
  };

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <h1 className="text-2xl font-bold text-on-surface tracking-tight mb-8">Settings</h1>

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
        </div>

        {loading ? (
          <div className="flex items-center gap-3 rounded-xl border border-outline-variant/10 bg-charcoal/50 px-5 py-6">
            <span className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            <span className="text-sm text-on-surface-variant/60">Loading accounts...</span>
          </div>
        ) : providers.length === 0 ? (
          <div className="rounded-xl border border-outline-variant/10 bg-charcoal/50 px-5 py-8 text-center">
            <Icon name="mail" className="text-3xl text-on-surface-variant/30 mb-2" />
            <p className="text-sm text-on-surface-variant/60">No Gmail accounts connected</p>
            <p className="text-xs text-on-surface-variant/40 mt-1">Connect a Gmail account to send and receive emails.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {providers.map((p) => {
              const health = healthMap[p.id];
              return (
                <div key={p.id} className="flex items-center justify-between rounded-xl border border-outline-variant/10 bg-charcoal/50 px-5 py-4">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-container/20 shrink-0">
                      <Icon name="mail" className="text-lg text-primary" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-on-surface truncate">{p.email || "Gmail"}</span>
                        <span className={`text-xs font-medium ${statusColor(p.status)}`}>{p.status}</span>
                      </div>
                      <div className="flex items-center gap-3 mt-0.5">
                        {health ? (
                          <>
                            <span className={`text-xs ${statusColor(health.status)}`}>{health.status}</span>
                            {health.last_sync && (
                              <span className="text-xs text-on-surface-variant/50">Last sync: {new Date(health.last_sync).toLocaleString()}</span>
                            )}
                          </>
                        ) : (
                          <span className="text-xs text-on-surface-variant/50">Health unknown</span>
                        )}
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => handleDisconnect(p.id)}
                    className="shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium text-error hover:bg-error/10 transition-colors"
                  >
                    Disconnect
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Account Info */}
      <section className="mb-10">
        <h2 className="text-lg font-semibold text-on-surface mb-4">Account</h2>
        <div className="rounded-xl border border-outline-variant/10 bg-charcoal/50 px-5 py-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-on-surface-variant/70">Session Token</span>
            <span className="text-sm font-mono text-on-surface/70 truncate max-w-[300px]">{sessionToken || "—"}</span>
          </div>
        </div>
      </section>
    </div>
  );
}
