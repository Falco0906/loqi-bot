"use client";

import { useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useIntelligenceWorkspace } from "../../hooks/useIntelligenceWorkspace";
import { selectAuthorizedWorkspace } from "../../lib/api";
import Icon from "../shared/Icon";

function workspaceUrl(pathname: string, current: URLSearchParams, workspaceId: string) {
  let params = new URLSearchParams(current);
  if (pathname === "/discovery") {
    // A search/run belongs to its original workspace. Switching scope starts
    // a clean Discover view; it never hydrates the previous workspace's run.
    params = new URLSearchParams();
    params.set("workspace_id", workspaceId);
    params.set("fresh", "1");
  } else if (pathname === "/discovery/history") {
    params = new URLSearchParams();
    params.set("workspace_id", workspaceId);
  } else if (pathname === "/lead-intelligence") {
    params.delete("lead_ids");
  } else if (pathname === "/campaigns/new") {
    // The pending lead handoff is scoped to the workspace that created it.
    params.delete("discovery");
    params.delete("return");
    params.delete("creation_key");
  }

  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

export default function WorkspaceSwitcher({ collapsed = false }: { collapsed?: boolean }) {
  const router = useRouter();
  const pathname = usePathname() || "/";
  const searchParams = useSearchParams();
  const requestedWorkspace = searchParams.get("workspace_id") || "";
  const context = useIntelligenceWorkspace(
    requestedWorkspace,
    pathname === "/discovery" || pathname === "/discovery/history",
  );
  const [isOpen, setIsOpen] = useState(false);
  const [pendingWorkspace, setPendingWorkspace] = useState("");
  const [selectionError, setSelectionError] = useState("");
  const selectionAttempt = useRef(0);
  const currentScope = useRef({ pathname, search: searchParams.toString(), scope: context.scope });
  currentScope.current = { pathname, search: searchParams.toString(), scope: context.scope };
  const currentWorkspace = context.workspaces.find((item) => item.id === context.workspace);
  const label = context.loading
    ? "Loading workspaces…"
    : currentWorkspace
      ? currentWorkspace.name || "Unnamed workspace"
      : requestedWorkspace ? "Workspace unavailable" : "Choose workspace";

  const chooseWorkspace = async (workspaceId: string) => {
    if (pendingWorkspace) return;
    if (workspaceId === context.workspace) { setIsOpen(false); return; }

    const attempt = ++selectionAttempt.current;
    const startingScope = currentScope.current;
    setPendingWorkspace(workspaceId);
    setSelectionError("");
    try {
      // The client list is for presentation only. The existing backend
      // selection endpoint independently checks the user's membership.
      await selectAuthorizedWorkspace(workspaceId);
      const activeScope = currentScope.current;
      if (
        attempt !== selectionAttempt.current
        || activeScope.pathname !== startingScope.pathname
        || activeScope.search !== startingScope.search
        || activeScope.scope !== startingScope.scope
      ) return;
      router.push(workspaceUrl(pathname, new URLSearchParams(searchParams.toString()), workspaceId));
      setIsOpen(false);
    } catch {
      if (attempt === selectionAttempt.current) {
        setSelectionError("That workspace is no longer accessible. Choose another workspace or reload the list.");
      }
    } finally {
      if (attempt === selectionAttempt.current) setPendingWorkspace("");
    }
  };

  return (
    <div className="relative mt-4">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-label={`Workspace: ${label}`}
        aria-expanded={isOpen}
        aria-haspopup="menu"
        disabled={context.loading}
        className={`flex w-full items-center rounded-lg border border-outline-variant/15 bg-surface-container-high/35 py-2 text-left transition-colors hover:border-outline-variant/30 hover:bg-surface-container-high/60 disabled:cursor-wait disabled:opacity-60 ${collapsed ? "justify-center px-1" : "gap-2 px-2"}`}
      >
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary-container text-[10px] font-bold text-on-primary">
          {(currentWorkspace?.name || "W").charAt(0).toUpperCase()}
        </span>
        {!collapsed && <span className="min-w-0 flex-1 truncate text-xs font-medium text-on-surface">{label}</span>}
        {!collapsed && <Icon name="expand_more" className="shrink-0 text-outline text-lg" />}
      </button>

      {isOpen && (
        <div role="menu" aria-label="Available workspaces" className={`absolute top-full z-50 mt-2 w-64 rounded-xl border border-outline-variant/20 bg-surface-container-high p-2 shadow-xl ${collapsed ? "left-0" : "left-0"}`}>
          <div className="px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-on-surface-variant/65">Switch workspace</div>
          {context.loading && <div role="status" className="px-2 py-3 text-sm text-on-surface-variant">Loading workspaces…</div>}
          {!context.loading && context.loadError && (
            <div className="px-2 py-2" role="alert">
              <p className="text-sm text-error">{context.loadError}</p>
              <button type="button" onClick={context.retry} className="mt-2 text-xs text-primary hover:underline">Try again</button>
            </div>
          )}
          {!context.loading && !context.loadError && context.workspaces.length === 0 && (
            <p className="px-2 py-3 text-sm text-on-surface-variant">No accessible workspaces are available for this account.</p>
          )}
          {!context.loading && !context.loadError && context.workspaces.map((workspace) => {
            const selected = workspace.id === context.workspace;
            return (
              <button
                key={workspace.id}
                type="button"
                role="menuitemradio"
                aria-checked={selected}
                disabled={Boolean(pendingWorkspace)}
                onClick={() => void chooseWorkspace(workspace.id)}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm text-on-surface transition-colors hover:bg-surface-container-highest disabled:opacity-60"
              >
                <span className="min-w-0 flex-1 truncate">{workspace.name || "Unnamed workspace"}</span>
                {pendingWorkspace === workspace.id ? <span role="status" className="text-xs text-on-surface-variant">Switching…</span> : selected ? <Icon name="check" className="text-base text-primary" /> : null}
              </button>
            );
          })}
          {!context.loading && requestedWorkspace && !context.workspace && !context.loadError && context.workspaces.length > 0 && (
            <p className="px-2 py-2 text-xs text-error" role="status">The requested workspace is unavailable. Choose an accessible workspace to continue.</p>
          )}
          {selectionError && <p role="alert" className="px-2 py-2 text-xs text-error">{selectionError}</p>}
        </div>
      )}
    </div>
  );
}
