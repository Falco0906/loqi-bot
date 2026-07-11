type Props = {
  label: string;
  value: string | number;
  subtitle?: string;
  trend?: "up" | "down" | "neutral";
  className?: string;
};

export default function MetricCard({ label, value, subtitle, trend, className = "" }: Props) {
  const trendColor =
    trend === "up"
      ? "text-secondary"
      : trend === "down"
        ? "text-error"
        : "text-on-surface-variant";

  return (
    <div className={`rounded-container border border-outline-variant/20 bg-surface-low p-4 ${className}`}>
      <div className="text-label-md uppercase tracking-[0.08em] text-on-surface-variant">
        {label}
      </div>
      <div className={`mt-1.5 text-headline-md font-medium ${trendColor}`}>
        {value}
      </div>
      {subtitle ? (
        <div className="mt-1 text-body-md text-on-surface-variant">
          {subtitle}
        </div>
      ) : null}
    </div>
  );
}
