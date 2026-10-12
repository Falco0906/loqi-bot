"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import DiscoveryDetailWorkspace from "../../../../components/dashboard/DiscoveryDetailWorkspace";
import { buildResearchUrl, parseDiscoveryMode, type CampaignAttachContext } from "../../../../lib/discovery-mode";
import { fetchDiscoveryFresh } from "../../../../lib/repositories";

function CampaignDiscoveryRedirect({ discoveryId, context }: { discoveryId: string; context: CampaignAttachContext }) {
  const router = useRouter();
  const [error, setError] = useState(false);
  const destination = buildResearchUrl(context);
  useEffect(() => {
    let active = true;
    fetchDiscoveryFresh(discoveryId).then((run) => {
      if (!active) return;
      if (!run) { setError(true); return; }
      router.replace(`${destination}&provider_discovery=${encodeURIComponent(run.id)}&q=${encodeURIComponent(run.query)}`);
    }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [discoveryId, destination, router]);
  return <div role={error ? "alert" : "status"} className="p-6">
    {error ? "This saved search is unavailable in the selected workspace." : "Opening Discover…"}
    {error && <Link href={destination} className="ml-2 text-primary underline">Return to Discover</Link>}
  </div>;
}

export default function DiscoveryDetailPage() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const mode = parseDiscoveryMode(searchParams);
  const discoveryId = params?.id ?? "";
  if (mode.mode === "campaign_attach" && mode.context) {
    return <CampaignDiscoveryRedirect discoveryId={discoveryId} context={mode.context} />;
  }
  return <DiscoveryDetailWorkspace discoveryId={discoveryId} />;
}
