type BadgeVariant = "default" | "primary" | "secondary" | "tertiary" | "error";

type Props = {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
};

const variants: Record<BadgeVariant, string> = {
  default:
    "bg-surface-highest text-on-surface-variant border border-outline-variant/30",
  primary:
    "bg-primary-container/10 text-primary border border-primary/20",
  secondary:
    "bg-secondary/10 text-secondary border border-secondary/20",
  tertiary:
    "bg-tertiary/10 text-tertiary border border-tertiary/20",
  error:
    "bg-error-container/20 text-error border border-error/20",
};

export default function Badge({ children, variant = "default", className = "" }: Props) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-label-md uppercase tracking-[0.08em] ${variants[variant]} ${className}`}
    >
      {children}
    </span>
  );
}
