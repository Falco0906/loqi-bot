"use client";

type Props = {
  title?: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
};

export default function PageSection({ title, description, children, className = "" }: Props) {
  return (
    <section className={`flex flex-col gap-4 ${className}`}>
      {(title || description) && (
        <div className="flex flex-col gap-0.5">
          {title && <h2 className="text-headline-sm text-on-surface">{title}</h2>}
          {description && <p className="text-body-sm text-outline">{description}</p>}
        </div>
      )}
      {children}
    </section>
  );
}