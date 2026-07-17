"use client";

import { ReactNode } from "react";

type Props = {
  children: ReactNode;
};

/*
 * WorkspaceContainer
 *
 * The future home of Loqi's scroll-based Workspace Navigation system.
 *
 * Currently renders children with consistent viewport sizing.
 * No behavior changes — architecture only.
 *
 * Future responsibilities (not yet implemented):
 *
 *   ─ Route transition manager
 *     Wrap children in AnimatePresence for enter/exit transitions.
 *     Key by route path so motion system detects page changes.
 *
 *   ─ Scroll snap controller
 *     Convert this container into a full-viewport scroll container
 *     with scroll-snap-type: y mandatory.
 *     Each workspace occupies 100vh.
 *
 *   ─ Workspace prefetching
 *     Prefetch adjacent workspace data when idle or on hover.
 *
 *   ─ Shared animation context
 *     Provide animation state (direction, progress, phase) to children
 *     so workspace pages can coordinate their own micro-animations.
 *
 *   ─ Workspace cache
 *     Keep up to 3 workspaces mounted: prev + current + next.
 *     Preserve scroll position and form state across navigations.
 *
 *   ─ Motion orchestration
 *     Coordinate shared element animations, parallax, and
 *     page-level transitions without layout breaking.
 *
 *   ─ Intersection observer
 *     Detect which workspace is currently in view.
 *     Update the route without a full navigation (router.replace).
 *     Update sidebar active state.
 *
 * Constraints for future implementation:
 *   - Must maintain 60 FPS
 *   - Must never block route changes (respond within 100ms)
 *   - Must never reload the App Shell (Sidebar, Topbar, context)
 *   - Must preserve workspace state (scroll, form data)
 *   - Must support independent routing (direct links, browser history)
 *   - Sidebar must remain functional as primary navigation
 *   - No animation libraries added in this phase
 */

export default function WorkspaceContainer({ children }: Props) {
  return (
    <div className="flex h-full flex-col">
      {children}
    </div>
  );
}
