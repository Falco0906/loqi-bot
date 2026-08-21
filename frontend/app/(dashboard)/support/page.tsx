"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

const SUPPORT_URL = "https://www.tryloqi.com/contact";

export default function SupportPage() {
  const router = useRouter();

  useEffect(() => {
    window.open(SUPPORT_URL, "_blank", "noopener,noreferrer");
    router.replace("/mission-control");
  }, [router]);

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center px-6">
      <p className="text-body-md text-on-surface-variant/80">Opening support in a new tab...</p>
      <a
        href={SUPPORT_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary hover:brightness-110 transition-all"
      >
        Open tryloqi.com/contact
      </a>
    </div>
  );
}
