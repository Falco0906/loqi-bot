"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "./useAuth";
import { listAuthorizedWorkspaces, type AuthorizedWorkspace } from "../lib/api";
import { rememberedDiscoveryWorkspace } from "../lib/discovery-context";

/** Resolve the existing membership-authorized workspace boundary before rendering
 * Discovery or Intelligence. No workspace or result authority is stored here.
 */
export function useIntelligenceWorkspace(requested: string, restoreDiscovery = false) {
  const { user } = useAuth();
  const identity = user?.id || "";
  const organization = user && "organization" in user ? user.organization?.id || "" : user && "orgId" in user ? user.orgId : "";
  const key = `${identity}:${organization}`;
  const [resolved, setResolved] = useState<{ key: string; version: number; workspaces: AuthorizedWorkspace[]; error: string }>({ key: "", version: -1, workspaces: [], error: "" });
  const [reloadVersion, setReloadVersion] = useState(0);
  useEffect(() => {
    if (!identity) return;
    const controller = new AbortController();
    void listAuthorizedWorkspaces(controller.signal).then(({ workspaces }) => {
      if (controller.signal.aborted) return;
      setResolved({ key, version: reloadVersion, workspaces, error: "" });
    }).catch(() => {
      if (!controller.signal.aborted) setResolved({ key, version: reloadVersion, workspaces: [], error: "Your workspace could not be loaded. Reload to try again." });
    });
    return () => controller.abort();
  }, [key, identity, reloadVersion]);
  const ready = resolved.key === key && resolved.version === reloadVersion;
  let remembered = "";
  if (ready && restoreDiscovery && !requested) {
    try { remembered = rememberedDiscoveryWorkspace(window.sessionStorage, identity, resolved.workspaces.map((item) => item.id)); } catch { /* Storage is optional. */ }
  }
  const selection = requested || remembered;
  const workspace = ready ? selection ? resolved.workspaces.find((item) => item.id === selection)?.id || "" : resolved.workspaces.length === 1 ? resolved.workspaces[0].id : "" : "";
  const selectedWorkspace = ready ? resolved.workspaces.find((item) => item.id === workspace) || null : null;
  const retry = useCallback(() => setReloadVersion((version) => version + 1), []);
  return {
    workspace,
    workspaceName: selectedWorkspace?.name || "",
    workspaces: ready ? resolved.workspaces : [],
    loading: Boolean(identity) && !ready,
    loadError: ready ? resolved.error : "",
    error: ready ? resolved.error || (workspace ? "" : "Choose an accessible workspace before continuing.") : "",
    retry,
    scope: `${identity}:${workspace}`,
  };
}
