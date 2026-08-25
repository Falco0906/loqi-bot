"use client";

import { useEffect, useState } from "react";
import BetaAccessModal from "../shared/BetaAccessModal";

const BETA_NOTICE_KEY = "loqi_beta_access_acknowledged";

export default function AuthBetaGate({ children }: { children: React.ReactNode }) {
  const [showBetaNotice, setShowBetaNotice] = useState(false);

  useEffect(() => {
    setShowBetaNotice(window.localStorage.getItem(BETA_NOTICE_KEY) !== "true");
  }, []);

  function acknowledgeBetaNotice() {
    window.localStorage.setItem(BETA_NOTICE_KEY, "true");
    setShowBetaNotice(false);
  }

  return (
    <>
      {children}
      {showBetaNotice && <BetaAccessModal onContinue={acknowledgeBetaNotice} />}
    </>
  );
}
