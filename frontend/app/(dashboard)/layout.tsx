"use client";

import { useState, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar, { SIDEBAR_EXPANDED_WIDTH, SIDEBAR_COLLAPSED_WIDTH } from "../../components/layout/Sidebar";
import Topbar from "../../components/layout/Topbar";
import CopilotPanel from "../../components/copilot/CopilotPanel";
import BackendOffline from "../../components/error/BackendOffline";
import ToastContainer from "../../components/shared/Toast";
import CommandBar from "../../components/layout/CommandBar";
import { useBackendHealth } from "../../hooks/useBackendHealth";
import { useAuth } from "../../hooks/useAuth";
import { CopilotProvider, useCopilot } from "../../contexts/CopilotContext";
import AppPage from "../../components/primitives/AppPage";
import { ProspectRegistryProvider } from "../../contexts/ProspectRegistryProvider";

const COPILOT_PANEL_WIDTH = 380;

function DashboardShell({ children }: { children: React.ReactNode }) {
  const [isCommandBarOpen, setIsCommandBarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarDragging, setSidebarDragging] = useState(false);
  const [sidebarPreview, setSidebarPreview] = useState(SIDEBAR_EXPANDED_WIDTH);

  const { open: copilotOpen } = useCopilot();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setIsCommandBarOpen((prev) => !prev);
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        toggleSidebar();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  useEffect(() => {
    setSidebarCollapsed(window.localStorage.getItem("loqi.sidebar.collapsed") === "true");
  }, []);

  useEffect(() => {
    window.localStorage.setItem("loqi.sidebar.collapsed", String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  function toggleSidebar() {
    setSidebarCollapsed((prev) => !prev);
  }

  const effectiveSidebarWidth = sidebarDragging
    ? sidebarPreview
    : sidebarCollapsed
      ? SIDEBAR_COLLAPSED_WIDTH
      : SIDEBAR_EXPANDED_WIDTH;

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
    <>
      <CommandBar isOpen={isCommandBarOpen} onClose={() => setIsCommandBarOpen(false)} />
      <div className="flex h-full overflow-hidden">
        <Sidebar
          collapsed={sidebarCollapsed}
          dragging={sidebarDragging}
          previewWidth={effectiveSidebarWidth}
          onDragStart={() => {
            setSidebarPreview(sidebarCollapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_EXPANDED_WIDTH);
            setSidebarDragging(true);
          }}
          onDragPreview={setSidebarPreview}
          onDragCommit={(expand) => {
            setSidebarDragging(false);
            setSidebarCollapsed(!expand);
          }}
          onToggleCollapse={toggleSidebar}
        />
        <div
          className={`flex flex-1 flex-col h-full ${sidebarDragging ? "" : "transition-[margin] duration-200 ease-out"}`}
          style={{
            marginLeft: effectiveSidebarWidth,
            "--sidebar-w": `${effectiveSidebarWidth}px`,
            "--copilot-w": !isDraftPage && copilotOpen ? `${COPILOT_PANEL_WIDTH}px` : "0px",
          } as React.CSSProperties}
        >
          <Topbar />
          <div className="flex flex-1 min-h-0">
            <main className="flex-1 overflow-y-auto h-full">
               {isDraftPage ? children : <AppPage>{children}</AppPage>}
            </main>
            {!isDraftPage && <CopilotPanel width={COPILOT_PANEL_WIDTH} />}
          </div>
          <ToastContainer />
        </div>
      </div>
    </>
  );
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ProspectRegistryProvider>
      <CopilotProvider>
        <DashboardShell>
          {children}
        </DashboardShell>
      </CopilotProvider>
    </ProspectRegistryProvider>
  );
}
