"use client";

import { Suspense } from "react";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { verifyEmail } from "../../../lib/auth-api";

type VerifyState = "loading" | "success" | "failed";

function VerifyEmailInner() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const [state, setState] = useState<VerifyState>("loading");

  useEffect(() => {
    if (!token) {
      setState("failed");
      return;
    }

    let cancelled = false;

    verifyEmail(token)
      .then(() => {
        if (!cancelled) setState("success");
      })
      .catch(() => {
        if (!cancelled) setState("failed");
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="flex w-full flex-col items-center text-center gap-6 animate-fade-in">
      {state === "loading" && (
        <>
          <div className="h-5 w-5 border-2 border-[#000000] border-t-transparent rounded-full animate-spin" />
          <p className="font-['Inter'] text-[16px] text-[#444748]">
            Verifying your email...
          </p>
        </>
      )}

      {state === "success" && (
        <>
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-[#ebe7e6]">
            <span className="material-symbols-outlined text-[28px] text-[#53625c]">check</span>
          </div>
          <div className="flex flex-col gap-1">
            <h1 className="font-['Libre_Caslon_Text'] text-[24px] text-[#000000]">
              Email verified
            </h1>
            <p className="font-['Inter'] text-[16px] text-[#444748]">
              Your account is now active.
              <br />
              Your session will continue automatically in the original tab.
            </p>
          </div>
        </>
      )}

      {state === "failed" && (
        <>
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-[#fef2f2]">
            <span className="material-symbols-outlined text-[28px] text-[#dc2626]">error</span>
          </div>
          <div className="flex flex-col gap-1">
            <h1 className="font-['Libre_Caslon_Text'] text-[24px] text-[#000000]">
              This verification link is invalid or has expired.
            </h1>
            <p className="font-['Inter'] text-[16px] text-[#444748]">
              Please request a new verification email.
            </p>
          </div>
        </>
      )}
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense
      fallback={
        <div className="flex w-full flex-col items-center gap-4 animate-fade-in pt-16">
          <div className="h-5 w-5 border-2 border-[#000000] border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <VerifyEmailInner />
    </Suspense>
  );
}
