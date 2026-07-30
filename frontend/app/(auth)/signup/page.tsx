"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../../hooks/useAuth";
import SignupForm from "../../../components/auth/SignupForm";
import Link from "next/link";

export default function SignupPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();
  const [submitted, setSubmitted] = useState(false);

  if (isLoading) {
    return (
      <div className="flex w-full flex-col items-center gap-4 animate-fade-in pt-16">
        <div className="h-5 w-5 border-2 border-[#000000] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (isAuthenticated) {
    return null;
  }

  if (submitted) {
    return null;
  }

  const handleEmailSubmitted = (sessionId: string) => {
    setSubmitted(true);
    router.push(`/check-email?session=${encodeURIComponent(sessionId)}`);
  };

  return (
    <div className="flex w-full flex-col gap-8 animate-fade-in">
      <div className="flex flex-col gap-3 text-center">
        <h1 className="font-['Libre_Caslon_Text'] text-[32px] leading-[1.3] text-[#000000] tracking-tight">
          Create Account
        </h1>
        <p className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748]">
          Start with Loqi
        </p>
      </div>

      <SignupForm onEmailSubmitted={handleEmailSubmitted} />

      <p className="text-center font-['Inter'] text-[14px] leading-[1.5] text-[#747878]">
        Already have an account?{" "}
        <Link
          href="/login"
          className="font-medium text-[#000000] hover:text-[#444748] transition-colors underline"
        >
          Sign in
        </Link>
      </p>
    </div>
  );
}
