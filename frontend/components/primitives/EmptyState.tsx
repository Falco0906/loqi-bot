"use client";

import PrimaryButton from "../shared/PrimaryButton";

type Props = {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
};

export default function EmptyState({ title, description, actionLabel, onAction }: Props) {
  return (
    <div className="flex flex-col items-center justify-center py-24 gap-6 text-center border border-dashed border-outline-variant/30 rounded-container bg-surface-lowest">
      <div className="flex flex-col gap-2 max-w-xs">
        <h3 className="text-body-lg font-semibold text-on-surface">{title}</h3>
        <p className="text-body-md text-outline">{description}</p>
      </div>
      {actionLabel && onAction && (
        <PrimaryButton onClick={onAction}>
          {actionLabel}
        </PrimaryButton>
      )}
    </div>
  );
}