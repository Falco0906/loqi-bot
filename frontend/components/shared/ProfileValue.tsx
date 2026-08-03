"use client";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function ProfileValue({
  value,
  className = "",
}: {
  value: unknown;
  className?: string;
}) {
  if (value == null) return null;

  if (typeof value === "string") {
    if (!value) return null;
    return <span className={className}>{value}</span>;
  }

  if (Array.isArray(value)) {
    return (
      <span className={className}>
        {value.map((item, i) => (
          <span key={i}>
            {typeof item === "string" ? item : JSON.stringify(item)}
            {i < value.length - 1 ? ", " : ""}
          </span>
        ))}
      </span>
    );
  }

  if (isRecord(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) return null;
    return (
      <div className={`space-y-2 ${className}`}>
        {entries.map(([key, val]) => (
          <div key={key} className="flex gap-3">
            <span className="text-[11px] uppercase tracking-[0.05em] font-semibold text-[#444748] min-w-[100px] shrink-0">
              {key}
            </span>
            <span className="font-['Inter'] text-[16px] leading-[1.5] text-[#1c1b1b]">
              {typeof val === "string"
                ? val
                : isRecord(val) || Array.isArray(val)
                  ? JSON.stringify(val, null, 1)
                  : String(val)}
            </span>
          </div>
        ))}
      </div>
    );
  }

  return <span className={className}>{String(value)}</span>;
}
