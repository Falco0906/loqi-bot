"use client";

import { useParams } from "next/navigation";
import DiscoveryDetailWorkspace from "../../../../components/dashboard/DiscoveryDetailWorkspace";

export default function DiscoveryDetailPage() {
  const params = useParams<{ id: string }>();
  const discoveryId = params?.id ?? "";
  return <DiscoveryDetailWorkspace discoveryId={discoveryId} />;
}