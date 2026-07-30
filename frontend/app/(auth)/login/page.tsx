"use client";

import { useAuth } from "../../../hooks/useAuth";
import LoginForm from "../../../components/auth/LoginForm";
import Link from "next/link";

export default function LoginPage() {
  const { isAuthenticated, isLoading } = useAuth();

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

  return (
    <div className="flex w-full flex-col gap-8 animate-fade-in">
      <div className="flex flex-col gap-3 text-center">
        <h1 className="font-['Libre_Caslon_Text'] text-[32px] leading-[1.3] text-[#000000] tracking-tight">
          Sign In
        </h1>
        <p className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748]">
          Welcome back to Loqi
        </p>
      </div>

      <LoginForm />

      <p className="text-center font-['Inter'] text-[14px] leading-[1.5] text-[#747878]">
        Don't have an account?{" "}
        <Link
          href="/signup"
          className="font-medium text-[#000000] hover:text-[#444748] transition-colors underline"
        >
          Sign up
        </Link>
      </p>
    </div>
  );
}
