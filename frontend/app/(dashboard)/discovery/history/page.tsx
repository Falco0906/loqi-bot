"use client";
import DiscoveryHistory from "../../../../components/dashboard/DiscoveryHistory";
import { useSearchParams } from "next/navigation";
import { useIntelligenceWorkspace } from "../../../../hooks/useIntelligenceWorkspace";

/** Provider-run research history remains available without competing with Discovery's lead browser. */
export default function DiscoveryHistoryPage() {
  const params = useSearchParams();
  const context = useIntelligenceWorkspace(params.get("workspace_id") || "", params.size === 0);
  if (!context.workspace) return <div role={context.error ? "alert" : "status"} className="p-6">{context.error || "Loading your workspace…"}</div>;
  return <DiscoveryHistory key={context.scope} workspaceId={context.workspace} />;
}
