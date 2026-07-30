"use client";

import { forwardRef, useId } from "react";

type Props = {
  label?: string;
  type?: "text" | "email" | "password" | "tel" | "url";
  placeholder?: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  disabled?: boolean;
  autoFocus?: boolean;
  autoComplete?: string;
  className?: string;
};

const Input = forwardRef<HTMLInputElement, Props>(
  (
    {
      label,
      type = "text",
      placeholder,
      value,
      onChange,
      error,
      disabled,
      autoFocus,
      autoComplete,
      className = "",
    },
    ref,
  ) => {
    const id = useId();

    return (
      <div className={`flex flex-col gap-1.5 ${className}`}>
        {label && (
          <label
            htmlFor={id}
            className="text-label-sm uppercase tracking-widest text-on-surface-variant"
          >
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={id}
          type={type}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          autoFocus={autoFocus}
          autoComplete={autoComplete}
          className={`h-10 w-full rounded-button border bg-surface-low px-3 text-sm text-on-surface placeholder:text-outline/50 transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-primary/40 ${
            error
              ? "border-error/60 focus:ring-error/40"
              : "border-outline-variant/30 hover:border-outline-variant/60 focus:border-primary/40"
          } disabled:cursor-not-allowed disabled:opacity-40`}
          aria-invalid={!!error}
          aria-describedby={error ? `${id}-error` : undefined}
        />
        {error && (
          <p id={`${id}-error`} className="text-body-sm text-error" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  },
);

Input.displayName = "Input";
export default Input;