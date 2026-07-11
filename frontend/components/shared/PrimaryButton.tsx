"use client";

type Props = {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
  type?: "button" | "submit";
};

export default function PrimaryButton({
  children,
  onClick,
  disabled,
  className = "",
  type = "button",
}: Props) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center rounded-button bg-primary px-4 py-2 text-sm font-semibold text-on-primary transition hover:brightness-110 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
    >
      {children}
    </button>
  );
}
