"use client";

import Sidebar from "../../components/layout/Sidebar";
import Topbar from "../../components/layout/Topbar";
import CommandBar from "../../components/layout/CommandBar";
import BackendOffline from "../../components/error/BackendOffline";
import { useBackendHealth } from "../../hooks/useBackendHealth";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { healthy, retry } = useBackendHealth();

  if (healthy === null) {
    return (
      <div className="flex h-full items-center justify-center bg-background">
        <div className="flex items-center gap-3 text-on-surface-variant">
          <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          Connecting to backend...
        </div>
      </div>
    );
  }

  if (healthy === false) {
    return <BackendOffline onRetry={retry} />;
  }

  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="ml-64 flex flex-1 flex-col">
        <Topbar />
        <main className="flex-1 overflow-y-auto pt-16">
          {children}
        </main>
        <CommandBar />
      </div>
    </div>
  );
}
