"use client";

import { useState } from "react";
import { useAuth } from "../../hooks/useAuth";
import { AuthApiError } from "../../lib/auth-api";

type Props = {
  onSuccess?: () => void;
};

export default function LoginForm({ onSuccess }: Props) {
  const { login, initiateGoogleLogin } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!email.trim()) {
      setError("Please enter your email address");
      return;
    }
    if (!password) {
      setError("Please enter your password");
      return;
    }

    setIsLoading(true);
    try {
      await login(email.trim(), password);
      onSuccess?.();
    } catch (err) {
      if (err instanceof AuthApiError) {
        if (err.status === 401) {
          setError("Invalid email or password");
        } else {
          setError(err.message);
        }
      } else {
        setError("Unable to connect. Please try again.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5" noValidate>
      <div>
        <label className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium text-[#444748] mb-2 block">
          Email
        </label>
        <input
          type="email"
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          disabled={isLoading}
          autoFocus
          className="w-full bg-[#ffffff] border border-[#c4c7c7] rounded-lg px-4 py-3 font-['Inter'] text-[16px] leading-[1.5] text-[#1c1b1b] placeholder:text-[#747878] focus:outline-none focus:ring-1 focus:ring-[#000000] focus:border-[#000000] transition-all disabled:opacity-50"
        />
      </div>

      <div>
        <label className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium text-[#444748] mb-2 block">
          Password
        </label>
        <input
          type="password"
          placeholder="Enter your password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          disabled={isLoading}
          className="w-full bg-[#ffffff] border border-[#c4c7c7] rounded-lg px-4 py-3 font-['Inter'] text-[16px] leading-[1.5] text-[#1c1b1b] placeholder:text-[#747878] focus:outline-none focus:ring-1 focus:ring-[#000000] focus:border-[#000000] transition-all disabled:opacity-50"
        />
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            className="font-['Inter'] text-[13px] text-[#747878] hover:text-[#000000] transition-colors cursor-pointer"
            onClick={() => {}}
            tabIndex={-1}
          >
            Forgot password?
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-[#fef2f2] border border-[#fecaca] rounded-lg px-4 py-3 font-['Inter'] text-[14px] text-[#dc2626]">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={isLoading}
        className="w-full bg-[#000000] text-[#ffffff] rounded-lg px-6 py-3 font-['Geist'] text-[14px] font-medium hover:bg-[#444748] active:scale-95 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
      >
        {isLoading ? (
          <>
            <span className="material-symbols-outlined text-sm animate-spin">refresh</span>
            Signing in...
          </>
        ) : (
          "Sign in"
        )}
      </button>

      <div className="relative flex items-center py-2">
        <div className="flex-grow border-t border-[#c4c7c7]"></div>
        <span className="flex-shrink mx-4 font-['Inter'] text-[13px] text-[#747878]">or</span>
        <div className="flex-grow border-t border-[#c4c7c7]"></div>
      </div>

      <button
        type="button"
        onClick={initiateGoogleLogin}
        className="w-full bg-[#ffffff] border border-[#c4c7c7] text-[#1c1b1b] rounded-lg px-6 py-3 font-['Geist'] text-[14px] font-medium hover:border-[#000000] hover:text-[#000000] active:scale-95 transition-all flex items-center justify-center gap-2"
      >
        <svg width="20" height="20" viewBox="0 0 24 24">
          <path
            fill="#4285F4"
            d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
          />
          <path
            fill="#34A853"
            d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
          />
          <path
            fill="#FBBC05"
            d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
          />
          <path
            fill="#EA4335"
            d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
          />
        </svg>
        Continue with Google
      </button>
    </form>
  );
}
