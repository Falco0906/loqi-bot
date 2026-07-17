import { Suspense } from "react";
import WorkspaceContainer from "../../../components/layout/WorkspaceContainer";
import DraftReviewWorkspace from "../../../components/draft/DraftReviewWorkspace";

function DraftFallback() {
  return (
    <div className="flex h-full overflow-hidden animate-fade-in">
      <aside className="w-72 shrink-0 border-r border-outline-variant/10 bg-surface-lowest p-4 space-y-3">
        <div className="h-5 w-24 animate-skeleton-pulse bg-surface-high/50 rounded-lg" />
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="flex items-start gap-2 animate-skeleton-pulse" style={{ animationDelay: `${i * 0.05}s` }}>
            <div className="w-8 h-8 rounded-lg bg-surface-high/50 shrink-0" />
            <div className="flex-1 space-y-1.5">
              <div className="h-3 w-28 bg-surface-high/50 rounded" />
              <div className="h-2 w-20 bg-surface-high/50 rounded" />
            </div>
          </div>
        ))}
      </aside>
      <section className="flex-1 p-6 space-y-4">
        <div className="h-4 w-48 animate-skeleton-pulse bg-surface-high/50 rounded-lg" />
        <div className="h-64 animate-skeleton-pulse bg-surface-highest/20 rounded-xl" />
        <div className="h-32 animate-skeleton-pulse bg-surface-highest/20 rounded-xl" />
      </section>
    </div>
  );
}

export default function DraftPage() {
  return (
    <WorkspaceContainer>
      <Suspense fallback={<DraftFallback />}>
        <DraftReviewWorkspace />
      </Suspense>
    </WorkspaceContainer>
  );
}
