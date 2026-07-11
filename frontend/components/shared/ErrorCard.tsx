"use client";

import Icon from "./Icon";

type Props = {
  title?: string;
  message: string;
  recovery?: string;
  actionLabel?: string;
  onAction?: () => void;
};

export default function ErrorCard({
  title = "Something went wrong",
  message,
  recovery,
  actionLabel,
  onAction,
}: Props) {
  return (
    <div className="rounded-xl border border-error/20 bg-error/5 px-5 py-4 animate-scale-in">
      <div className="flex items-start gap-3">
        <Icon name="warning" className="text-error text-lg mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-body-md text-on-surface font-bold mb-1">{title}</p>
          <p className="text-label-sm text-on-surface-variant/70 leading-relaxed">{message}</p>
          {recovery && (
            <p className="text-label-sm text-on-surface-variant/50 mt-1.5 leading-relaxed">{recovery}</p>
          )}
          {actionLabel && onAction && (
            <button
              type="button"
              onClick={onAction}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-error/30 px-3.5 py-1.5 text-label-sm font-semibold text-error hover:bg-error/5 transition-all active:scale-[0.97]"
            >
              <Icon name="refresh" className="text-sm" />
              {actionLabel}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
