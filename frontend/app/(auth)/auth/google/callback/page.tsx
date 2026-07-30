"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "../../../../../hooks/useAuth";

function GoogleCallbackInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { handleOAuthCallback } = useAuth();
  const [error, setError] = useState("");

  useEffect(() => {
    const code = searchParams.get("code");
    const state = searchParams.get("state");

    if (!code || !state) {
      setError("Missing code or state");
      return;
    }

    (async () => {
        try {
            await handleOAuthCallback(code, state);
        } catch (err) {
            setError("Authentication failed");
        }
    })();
  }, [searchParams, router, handleOAuthCallback]);

  if (error) return <div>{error}</div>;
  return <div>Authenticating...</div>;
}

export default function GoogleCallbackPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <GoogleCallbackInner />
    </Suspense>
  );
}
