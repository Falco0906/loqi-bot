type Props = {
  title: string;
  description?: string;
  className?: string;
};

export default function PlaceholderSection({
  title,
  description,
  className = "",
}: Props) {
  return (
    <div
      className={`rounded-container border border-dashed border-outline-variant/20 bg-surface-lowest/50 p-8 text-center ${className}`}
    >
      <div className="text-headline-md text-on-surface-variant/50">{title}</div>
      {description ? (
        <p className="mt-2 text-body-md text-on-surface-variant/30">
          {description}
        </p>
      ) : null}
    </div>
  );
}
