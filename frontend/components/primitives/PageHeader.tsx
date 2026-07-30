"use client";

type Props = {
  title: string;
  description?: string;
  actions?: React.ReactNode;
};

export default function PageHeader({ title, description, actions }: Props) {
  return (
    <div className="flex items-center justify-between gap-4 pb-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-headline-md text-on-surface">{title}</h1>
        {description && (
          <p className="text-body-md text-outline">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-3">{actions}</div>}
    </div>
  );
}