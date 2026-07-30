"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "../../../hooks/useAuth";
import CheckEmailContent from "../../../components/auth/CheckEmailContent";

function CheckEmailInner() {
  const searchParams = useSearchParams();
  const sessionIdFromUrl = searchParams.get("session");
  const { getPendingRegistration } = useAuth();

  const pending = getPendingRegistration();
  const resolvedSessionId = sessionIdFromUrl || pending?.registrationSessionId || "";
  const email = pending?.email || "";
  const showWarning =
    sessionIdFromUrl && pending && sessionIdFromUrl !== pending.registrationSessionId;

  return (
    <div className="flex w-full flex-col gap-6 animate-fade-in">
      {showWarning && (
        <div className="bg-[#fef2f2] border border-[#fecaca] rounded-lg px-4 py-3 font-['Inter'] text-[14px] text-[#dc2626] text-center">
          Session mismatch. Please sign up again.
        </div>
      )}
      <CheckEmailContent email={email} sessionId={resolvedSessionId} />

      <p className="text-center font-['Inter'] text-[14px] text-[#747878]">
        Did not receive the email? Check your spam folder
      </p>
    </div>
  );
}

export default function CheckEmailPage() {
  return (
    <Suspense
      fallback={
        <div className="flex w-full flex-col items-center gap-4 animate-fade-in pt-16">
          <div className="h-5 w-5 border-2 border-[#000000] border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <CheckEmailInner />
    </Suspense>
  );
}
