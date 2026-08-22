"use client";

import { useState, useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar, { SIDEBAR_EXPANDED_WIDTH, SIDEBAR_COLLAPSED_WIDTH } from "../../components/layout/Sidebar";
import Topbar from "../../components/layout/Topbar";
import CopilotPanel from "../../components/copilot/CopilotPanel";
import BackendOffline from "../../components/error/BackendOffline";
import ToastContainer from "../../components/shared/Toast";
import CommandBar from "../../components/layout/CommandBar";
import { useBackendHealth } from "../../hooks/useBackendHealth";
import { useAuth } from "../../hooks/useAuth";
import { useTextHighlight } from "../../hooks/useTextHighlight";
import { CopilotProvider, useCopilot } from "../../contexts/CopilotContext";
import { SearchProvider, useWorkspaceSearch } from "../../contexts/SearchContext";
import { startEventStream, stopEventStream, onServerEvent, type ServerEvent } from "../../lib/event-client";
import { invalidateClientCache, scopedKey } from "../../lib/client-cache";
import {
  invalidateMissionControlCache,
  invalidateDiscoveryCache,
} from "../../lib/repositories";
import AppPage from "../../components/primitives/AppPage";
import { ProspectRegistryProvider } from "../../contexts/ProspectRegistryProvider";

const COPILOT_PANEL_WIDTH = 380;
const HIGHLIGHT_PAGES = ["/mission-control", "/knowledge", "/strategic-update", "/settings"];

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
  const { query: searchQuery } = useWorkspaceSearch();

  const isDraftPage = pathname?.startsWith("/draft");
  const isHighlightPage = !!pathname && HIGHLIGHT_PAGES.some((p) => pathname.startsWith(p));

  const mainRef = useRef<HTMLElement>(null);
  useTextHighlight(searchQuery, mainRef, isHighlightPage);

  // ── PR-3D: real-time event stream → targeted cache invalidation ──
  useEffect(() => {
    if (!isAuthenticated || isLoading) return;
    startEventStream();
    return () => stopEventStream();
  }, [isAuthenticated, isLoading]);

  useEffect(() => {
    // Narrowly-scoped invalidation: events mark relevant client-cache keys
    // stale; the next mount/refetch pulls authoritative data via REST.
    const handle = (event: ServerEvent) => {
      const token = localStorage.getItem("loqi_active_session_token");
      switch (event.type) {
        case "job.completed":
        case "job.progress":
          invalidateClientCache(scopedKey(token, "campaigns"));
          invalidateClientCache(scopedKey(token, "campaigns-meta"));
          invalidateDiscoveryCache();
          invalidateMissionControlCache();
          break;
        case "provider.connected":
        case "provider.disconnected":
          // Provider list cache lives server-side; identity cache is
          // invalidated backend-side. Nothing client-side to drop today.
          break;
        default:
          break;
      }
    };
    return onServerEvent(handle);
  }, []);

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
            <main ref={mainRef} className="flex-1 overflow-y-auto h-full">
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
        <SearchProvider>
          <DashboardShell>
            {children}
          </DashboardShell>
        </SearchProvider>
      </CopilotProvider>
    </ProspectRegistryProvider>
  );
}
