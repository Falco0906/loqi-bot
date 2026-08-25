"use client";

import { useEffect, useState } from "react";
import BetaAccessModal from "../shared/BetaAccessModal";

export default function AuthBetaGate({ children }: { children: React.ReactNode }) {
  const [showBetaNotice, setShowBetaNotice] = useState(false);

  useEffect(() => {
    setShowBetaNotice(true);
  }, []);

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
