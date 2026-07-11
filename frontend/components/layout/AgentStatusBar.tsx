type Props = {
  status?: "idle" | "working" | "error";
  message?: string;
  className?: string;
};

const statusConfig = {
  idle: {
    dot: "bg-on-surface-variant/40",
    ping: "bg-on-surface-variant/20",
    text: "text-on-surface-variant/60",
  },
  working: {
    dot: "bg-secondary",
    ping: "bg-secondary",
    text: "text-secondary",
  },
  error: {
    dot: "bg-error",
    ping: "bg-error",
    text: "text-error",
  },
};

export default function AgentStatusBar({
  status = "idle",
  message = "AI agent ready",
  className = "",
}: Props) {
  const cfg = statusConfig[status];

  return (
    <div
      className={`inline-flex items-center gap-2.5 rounded-xl border border-primary/20 bg-primary-container/5 px-4 py-2 ${className}`}
    >
      <span className="relative flex h-2.5 w-2.5">
        <span
          className={`absolute inline-flex h-full w-full animate-ping-slow rounded-full opacity-75 ${cfg.ping}`}
        />
        <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${cfg.dot}`} />
      </span>
      <span className={`text-body-md font-medium ${cfg.text}`}>{message}</span>
    </div>
  );
}
