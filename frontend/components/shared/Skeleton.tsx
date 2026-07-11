type Props = {
  className?: string;
  variant?: "text" | "card" | "avatar" | "button";
};

export default function Skeleton({ className = "", variant = "text" }: Props) {
  const base = "animate-skeleton-pulse bg-surface-high/50 rounded-lg";

  if (variant === "text") {
    return <div className={`${base} h-4 w-full ${className}`} />;
  }

  if (variant === "card") {
    return (
      <div className={`${base} h-32 w-full rounded-2xl ${className}`}>
        <div className="p-5 space-y-3">
          <div className="h-4 w-2/3 bg-surface-highest/30 rounded-lg" />
          <div className="h-3 w-1/2 bg-surface-highest/30 rounded-lg" />
          <div className="h-3 w-3/4 bg-surface-highest/30 rounded-lg" />
        </div>
      </div>
    );
  }

  if (variant === "avatar") {
    return <div className={`${base} h-10 w-10 rounded-full shrink-0 ${className}`} />;
  }

  if (variant === "button") {
    return <div className={`${base} h-9 w-28 rounded-lg ${className}`} />;
  }

  return <div className={`${base} ${className}`} />;
}
