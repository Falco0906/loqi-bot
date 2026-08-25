"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import BetaAccessModal from "../shared/BetaAccessModal";

export default function AuthBetaGate({ children }: { children: React.ReactNode }) {
  const [showBetaNotice, setShowBetaNotice] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    setShowBetaNotice(true);
  }, [pathname]);

  function acknowledgeBetaNotice() {
    setShowBetaNotice(false);
  }

  return (
    <>
      {children}
      {showBetaNotice && <BetaAccessModal onContinue={acknowledgeBetaNotice} />}
    </>
  );
}
