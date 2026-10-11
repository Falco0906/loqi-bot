"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "./useAuth";
import { listAuthorizedWorkspaces, type AuthorizedWorkspace } from "../lib/api";

/** Campaign URLs request scope; the authorized listing and backend enforce access.
 * Unlike Discovery, plain campaign URLs never infer scope from search history.
 * With multiple memberships an explicit workspace_id is required.
 */
export function useCampaignWorkspace(requested: string) {
  const { user, isLoading: authLoading } = useAuth();
  const identity = user?.id || "";
  const organization = user && "organization" in user ? user.organization?.id || "" : user && "orgId" in user ? user.orgId : "";
  const key = JSON.stringify([identity, organization, requested]);
  const [version, setVersion] = useState(0);
  const requestVersion = useRef(0);
  const [resolved, setResolved] = useState<{ key: string; version: number; workspaces: AuthorizedWorkspace[]; error: string }>({ key: "", version: -1, workspaces: [], error: "" });

  useEffect(() => {
    const generation = ++requestVersion.current;
    if (!identity || authLoading) return;
    const controller = new AbortController();
    const current = () => !controller.signal.aborted && generation === requestVersion.current;
    void listAuthorizedWorkspaces(controller.signal).then(({ workspaces }) => {
      if (current()) setResolved({ key, version, workspaces, error: "" });
    }).catch(() => {
      if (current()) setResolved({ key, version, workspaces: [], error: "Your workspace could not be loaded. Retry to try again." });
    });
    return () => { controller.abort(); ++requestVersion.current; };
  }, [key, identity, version, authLoading]);

  const ready = !authLoading && Boolean(identity) && resolved.key === key && resolved.version === version;
  const workspaces = ready ? resolved.workspaces : [];
  const selected = requested ? workspaces.find((item) => item.id === requested) : workspaces.length === 1 ? workspaces[0] : undefined;
  const workspace = selected?.id || "";
  const error = authLoading ? "" : !identity ? "Sign in before continuing." : !ready ? "" : resolved.error || (workspace ? "" : requested ? "This workspace is unavailable or inaccessible. Choose an accessible workspace." : workspaces.length ? "Choose a workspace explicitly before continuing." : "No accessible workspace is available.");
  const retry = useCallback(() => setVersion((value) => value + 1), []);
  // Preserve the existing page/cache scope convention; organization and URL
  // changes still invalidate requests through the separate resolution key.
  return { workspace, workspaceName: selected?.name || "", workspaces, loading: authLoading || Boolean(identity) && !ready, error, retry, scope: `${identity}:${workspace}` };
}
