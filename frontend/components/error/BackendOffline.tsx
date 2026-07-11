"use client";

import Icon from "../shared/Icon";

type Props = {
  onRetry?: () => void;
};

export default function BackendOffline({ onRetry }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background">
      <div className="max-w-md text-center px-6">
        <div className="w-20 h-20 rounded-2xl bg-error/10 flex items-center justify-center text-error mx-auto mb-6">
          <Icon name="cloud_off" className="text-5xl" />
        </div>
        <h1 className="text-headline-lg text-on-surface font-bold mb-2">
          Loqi Backend Offline
        </h1>
        <p className="text-body-md text-on-surface-variant/70 mb-8 leading-relaxed">
          Unable to reach the AI engine. Make sure the backend server is running on port 10000.
        </p>
        <div className="flex flex-col items-center gap-3">
          {onRetry && (
            <button
              onClick={onRetry}
              className="px-8 py-3 rounded-xl bg-primary text-on-primary font-bold hover:brightness-110 active:scale-95 transition-all text-sm"
            >
              <Icon name="refresh" className="inline-block mr-2 text-base" />
              Retry
            </button>
          )}
          <details className="text-left max-w-sm">
            <summary className="text-label-sm text-on-surface-variant/50 cursor-pointer hover:text-on-surface-variant/80 transition-colors">
              Restart Guide
            </summary>
            <div className="mt-3 p-4 rounded-xl bg-surface-high/30 text-label-sm text-on-surface-variant/70 space-y-2">
              <p>1. Open a terminal in the project root.</p>
              <p>2. Run: <code className="bg-surface-high/50 px-2 py-0.5 rounded text-primary font-mono">npm run dev</code></p>
              <p>3. Or start the backend separately:</p>
              <p className="pl-4"><code className="bg-surface-high/50 px-2 py-0.5 rounded text-primary font-mono">cd backend &amp;&amp; python main.py</code></p>
              <p>4. Wait for "Uvicorn running" log line.</p>
              <p>5. Refresh this page.</p>
            </div>
          </details>
        </div>
      </div>
    </div>
  );
}
