"use client";

type Props = {
  onContinue: () => void;
};

export default function BetaAccessModal({ onContinue }: Props) {
  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-obsidian/75 px-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="beta-access-title"
      aria-describedby="beta-access-description"
    >
      <div className="w-full max-w-md rounded-2xl border border-outline-variant/20 bg-surface-container-low p-6 shadow-2xl sm:p-8">
        <div className="mb-5 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <span className="material-symbols-outlined text-xl">science</span>
          </div>
          <span className="rounded-full border border-primary/20 bg-primary/5 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.14em] text-primary/70">
            Beta access
          </span>
        </div>

        <h1 id="beta-access-title" className="font-serif text-2xl tracking-tight text-on-surface">
          Loqi is currently in Beta
        </h1>
        <p id="beta-access-description" className="mt-4 text-sm leading-6 text-on-surface-variant">
          You&apos;re accessing the beta version of Loqi. External integrations are not yet connected to this environment, so some data and workflows are for demonstration purposes only.
        </p>
        <p className="mt-3 text-sm leading-6 text-on-surface-variant">
          Access is currently available to users who have completed a demo with the Loqi team.
        </p>

        <button
          type="button"
          onClick={onContinue}
          className="mt-7 w-full rounded-xl bg-primary px-4 py-3 text-sm font-bold text-on-primary transition-opacity hover:opacity-85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        >
          Continue to Beta
        </button>
      </div>
    </div>
  );
}
