"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useAuth } from "../../hooks/useAuth";
import { getRegistrationStatus, AuthApiError } from "../../lib/auth-api";

type Props = {
  email: string;
  sessionId: string;
};

type Step = "polling" | "verified" | "completing" | "signing_in" | "redirecting" | "error" | "retry_password";

export default function CheckEmailContent({ email, sessionId }: Props) {
  const { completeRegistration, getPendingRegistration, storePendingRegistration } = useAuth();
  const [step, setStep] = useState<Step>("polling");
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleComplete = useCallback(async (pwd?: string) => {
    const pending = getPendingRegistration();
    if (!pending) {
      setError("Registration data lost. Please sign up again.");
      setStep("error");
      return;
    }

    const passwordToUse = pwd || pending.password;
    setStep("completing");
    setError(null);
    try {
      setStep("signing_in");
      await completeRegistration(
        sessionId,
        pending.displayName,
        passwordToUse,
        pending.organizationName,
      );
      setStep("redirecting");
    } catch (err: any) {
      if (err instanceof AuthApiError && err.code === "PASSWORD_POLICY_VIOLATION") {
        setError(err.message);
        setStep("retry_password");
      } else {
        setError(err.message || "Failed to complete registration.");
        setStep("error");
      }
    }
  }, [completeRegistration, getPendingRegistration, sessionId]);

  const handleRetryPassword = () => {
    const pending = getPendingRegistration();
    if (!pending) return;
    
    // Validate new password (same logic as SignupForm)
    if (password.length < 12 || !/[A-Z]/.test(password) || !/[a-z]/.test(password) || !/[0-9]/.test(password) || !/[^A-Za-z0-9]/.test(password)) {
      setError("Password does not meet requirements (min 12 chars, upper, lower, digit, special)");
      return;
    }

    storePendingRegistration({ ...pending, password });
    handleComplete(password);
  };

  useEffect(() => {
    // PR-P1.4: in-flight guard — never overlap registration-status polls.
    let pollBusy = false;
    pollingRef.current = setInterval(async () => {
      if (pollBusy) return;
      pollBusy = true;
      try {
        const res = await getRegistrationStatus(sessionId);
        if (res.status === "verified" || res.status === "completed") {
          if (pollingRef.current) clearInterval(pollingRef.current);
          setStep("verified");
        }
      } catch {
        /* poll will retry */
      } finally {
        pollBusy = false;
      }
    }, 2000);

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [sessionId]);

  useEffect(() => {
    if (step === "verified") {
      handleComplete();
    }
  }, [step, handleComplete]);

  return (
    <div className="flex flex-col items-center text-center gap-6">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-[#ebe7e6]">
        {step === "polling" ? (
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[#444748] animate-pulse">
            <rect x="2" y="4" width="20" height="16" rx="2" />
            <path d="M22 7l-10 7L2 7" />
          </svg>
        ) : step === "redirecting" ? (
          <span className="material-symbols-outlined text-[28px] text-[#000000]">arrow_forward</span>
        ) : step === "error" ? (
          <span className="material-symbols-outlined text-[28px] text-[#dc2626]">error</span>
        ) : (
          <span className="material-symbols-outlined text-[28px] text-[#53625c]">check</span>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <h1 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#000000]">
          {step === "polling" && "Check your email"}
          {(step === "verified" || step === "completing") && "Email verified"}
          {step === "signing_in" && "Signing you in..."}
          {step === "redirecting" && "Redirecting..."}
          {step === "error" && "We couldn't finish creating your account."}
          {step === "retry_password" && "Password update needed"}
        </h1>
        <p className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748] max-w-sm">
          {step === "polling" && `We sent a verification link to ${email}. Click the link to activate your account.`}
          {(step === "verified" || step === "completing") && "Completing your account..."}
          {step === "signing_in" && "Setting up your workspace."}
          {step === "error" && error}
          {step === "retry_password" && "Your password didn't meet our security requirements. Please enter a new one."}
        </p>
      </div>

      {step === "retry_password" && (
        <div className="w-full max-w-sm flex flex-col gap-4">
          <div>
            <label className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium text-[#444748] mb-2 block text-left">
              New Password
            </label>
            <input
              type="password"
              placeholder="Enter new password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-[#ffffff] border border-[#c4c7c7] rounded-lg px-4 py-3 font-['Inter'] text-[16px] leading-[1.5] text-[#1c1b1b] placeholder:text-[#747878] focus:outline-none focus:ring-1 focus:ring-[#000000] focus:border-[#000000] transition-all"
            />
          </div>
          {error && <p className="font-['Inter'] text-[13px] text-[#dc2626]">{error}</p>}
          <button
            onClick={handleRetryPassword}
            className="w-full bg-[#000000] text-[#ffffff] rounded-lg px-6 py-3 font-['Geist'] text-[14px] font-medium hover:bg-[#444748] active:scale-95 transition-all"
          >
            Update Password & Retry
          </button>
        </div>
      )}

      {step === "polling" && (
        <p className="font-['Inter'] text-[13px] text-[#747878] flex items-center gap-2">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#000000] animate-pulse" />
          Waiting for verification...
        </p>
      )}

      {step === "error" && (
        <button
          onClick={() => handleComplete()}
          className="bg-[#000000] text-[#ffffff] rounded-lg px-6 py-3 font-['Geist'] text-[14px] font-medium hover:bg-[#444748] active:scale-95 transition-all"
        >
          Retry
        </button>
      )}
    </div>
  );
}
