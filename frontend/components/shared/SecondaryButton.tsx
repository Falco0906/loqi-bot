"use client";

import { useState } from "react";

type Props = {
  children: React.ReactNode;
  onClick?: () => void | Promise<void>;
  disabled?: boolean;
  loading?: boolean;
  className?: string;
};

export default function SecondaryButton({
  children,
  onClick,
  disabled,
  loading: externalLoading,
  className = "",
}: Props) {
  const [internalLoading, setInternalLoading] = useState(false);
  const isLoading = externalLoading ?? internalLoading;

  const handleClick = async () => {
    if (isLoading || disabled) return;
    if (!onClick) return;
    if (externalLoading === undefined) {
      setInternalLoading(true);
      try {
        await onClick();
      } finally {
        setInternalLoading(false);
      }
    } else {
      await onClick();
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled || isLoading}
      className={`inline-flex items-center justify-center rounded-button border border-outline-variant/30 bg-surface-container-high px-4 py-2 text-sm font-semibold text-on-surface transition-all duration-150 hover:border-primary/40 hover:brightness-110 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2 ${className}`}
    >
      {isLoading && (
        <svg
          className="-ml-1 mr-2 h-4 w-4 animate-spin text-on-surface/60"
          fill="none"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )}
      {children}
    </button>
  );
}
