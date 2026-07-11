type Props = {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  className?: string;
};

export default function SectionHeader({ title, subtitle, action, className = "" }: Props) {
  return (
    <div className={`flex items-start justify-between gap-4 ${className}`}>
      <div>
        <h2 className="text-headline-md text-on-surface">{title}</h2>
        {subtitle ? (
          <p className="mt-1 text-body-md text-on-surface-variant">{subtitle}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
