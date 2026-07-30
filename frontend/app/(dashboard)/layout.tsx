"use client";

import { useState, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar from "../../components/layout/Sidebar";
import Topbar from "../../components/layout/Topbar";
import CopilotPanel from "../../components/copilot/CopilotPanel";
import BackendOffline from "../../components/error/BackendOffline";
import ToastContainer from "../../components/shared/Toast";
import CommandBar from "../../components/layout/CommandBar";
import { useBackendHealth } from "../../hooks/useBackendHealth";
import { useAuth } from "../../hooks/useAuth";
import { CopilotProvider } from "../../contexts/CopilotContext";
import AppPage from "../../components/primitives/AppPage";
import { ProspectRegistryProvider } from "../../contexts/ProspectRegistryProvider";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [isCommandBarOpen, setIsCommandBarOpen] = useState(false);
  
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setIsCommandBarOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);
  
  const pathname = usePathname();
  const router = useRouter();
  const { healthy, retry } = useBackendHealth();
  const { user, isAuthenticated, isLoading } = useAuth();

  const isDraftPage = pathname?.startsWith("/draft");

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push("/login");
    }
  }, [isAuthenticated, isLoading, router]);

  useEffect(() => {
    if (!isLoading && isAuthenticated && user) {
      if ("onboarding_complete" in user && !user.onboarding_complete) {
        router.push("/onboarding");
      }
    }
  }, [isAuthenticated, isLoading, user, router]);

  if (isLoading || !isAuthenticated) {
    return (
      <div className="flex h-full items-center justify-center bg-obsidian">
        <div className="flex flex-col items-center gap-4 animate-fade-in">
          <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    );
  }

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
    <ProspectRegistryProvider>
      <CopilotProvider initialToken={null}>
        <CommandBar isOpen={isCommandBarOpen} onClose={() => setIsCommandBarOpen(false)} />
        <div className="flex h-full overflow-hidden">
          <Sidebar />
          <div className="ml-64 flex flex-1 flex-col h-full">
            <Topbar />
            <main className="flex-1 overflow-y-auto pt-16 h-full">
               <AppPage>
                  {children}
               </AppPage>
            </main>
            <ToastContainer />
            {!isDraftPage && <CopilotPanel />}
          </div>
        </div>
      </CopilotProvider>
    </ProspectRegistryProvider>
  );
}
