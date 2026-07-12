"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import Sidebar from "../../components/layout/Sidebar";
import Topbar from "../../components/layout/Topbar";
import CopilotPanel from "../../components/copilot/CopilotPanel";
import BackendOffline from "../../components/error/BackendOffline";
import ToastContainer from "../../components/shared/Toast";
import { useBackendHealth } from "../../hooks/useBackendHealth";
import { CopilotProvider } from "../../contexts/CopilotContext";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const { healthy, retry } = useBackendHealth();
  const [sessionToken, setSessionToken] = useState<string | null>(null);

  const isDraftPage = pathname?.startsWith("/draft");

  useEffect(() => {
    const token = (() => {
      try { return localStorage.getItem(ACTIVE_SESSION_KEY); }
      catch { return null; }
    })();
    setSessionToken(token);
  }, []);

  if (healthy === null) {
    return (
      <div className="flex h-full items-center justify-center bg-obsidian">
        <div className="flex flex-col items-center gap-4 animate-fade-in">
          <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  if (healthy === false) {
    return <BackendOffline onRetry={retry} />;
  }

  return (
    <CopilotProvider initialToken={sessionToken}>
      <div className="flex h-full">
        <Sidebar />
        <div className="ml-64 flex flex-1 flex-col">
          <Topbar />
          <main className="flex-1 overflow-y-auto pt-16">
            {children}
          </main>
          <ToastContainer />
          {!isDraftPage && <CopilotPanel />}
        </div>
      </div>
    </CopilotProvider>
  );
}
