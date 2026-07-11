"use client";

type Props = {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
};

export default function SecondaryButton({
  children,
  onClick,
  disabled,
  className = "",
}: Props) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center rounded-button border border-outline-variant/30 bg-[#1F1F23] px-4 py-2 text-sm font-semibold text-on-surface transition hover:border-primary/40 hover:brightness-110 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
    >
      {children}
    </button>
  );
}
