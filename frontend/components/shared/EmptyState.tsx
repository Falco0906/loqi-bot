import Icon from "./Icon";

type Action = {
  label: string;
  onClick?: () => void;
  href?: string;
  variant?: "primary" | "secondary";
};

type Props = {
  icon: string;
  title: string;
  description: string;
  action?: Action;
  secondaryAction?: Action;
};

function ActionButton({ action }: { action: Action }) {
  const base = "inline-flex items-center justify-center rounded-lg px-4 py-2 text-sm font-semibold transition-all duration-150 focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2";
  const styles = action.variant === "primary" || !action.variant
    ? "bg-primary text-on-primary hover:brightness-110 active:scale-[0.97]"
    : "border border-outline-variant/30 text-on-surface hover:border-primary/40 hover:text-primary active:scale-[0.97]";

  if (action.href) {
    return <a href={action.href} className={`${base} ${styles}`}>{action.label}</a>;
  }
  return (
    <button type="button" onClick={action.onClick} className={`${base} ${styles}`}>
      {action.label}
    </button>
  );
}

export default function EmptyState({ icon, title, description, action, secondaryAction }: Props) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center animate-fade-in">
      <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
        <Icon name={icon} className="text-3xl" />
      </div>
      <p className="text-body-lg text-on-surface-variant/80 font-medium">{title}</p>
      <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-md leading-relaxed">{description}</p>
      {(action || secondaryAction) && (
        <div className="flex items-center gap-3 mt-6">
          {action && <ActionButton action={action} />}
          {secondaryAction && <ActionButton action={secondaryAction} />}
        </div>
      )}
    </div>
  );
}
