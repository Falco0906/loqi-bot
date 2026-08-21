"use client";

import Link from "next/link";
import { useCallback, useRef, type KeyboardEvent, type PointerEvent } from "react";
import { usePathname } from "next/navigation";
import Icon from "../shared/Icon";
import { useAuth } from "../../hooks/useAuth";
import { useWorkspaceSearch } from "../../contexts/SearchContext";
import { pageConfig } from "./Topbar";

const navigation = [
  { label: "Mission Control", href: "/mission-control", icon: "dashboard" },
  { label: "Discovery", href: "/discovery", icon: "explore" },
  { label: "Campaigns", href: "/campaigns", icon: "campaign" },
  { label: "Draft Review", href: "/draft", icon: "draft" },
  { label: "Inbox", href: "/inbox", icon: "inbox" },
];

const utilityPages = [
  { label: "Knowledge", href: "/knowledge", icon: "psychology" },
  { label: "Strategic Update", href: "/strategic-update", icon: "auto_awesome" },
  { label: "Settings", href: "/settings", icon: "settings" },
  { label: "Support", href: "https://www.tryloqi.com/contact", icon: "help_outline", external: true },
];

export const SIDEBAR_EXPANDED_WIDTH = 256;
export const SIDEBAR_COLLAPSED_WIDTH = 68;

/* How far (px) the handle must travel past its origin to flip state on release */
const COMMIT_THRESHOLD = 48;
/* Rubber-band resistance applied beyond the two state widths */
const ELASTIC_RESISTANCE = 0.15;
const ELASTIC_MAX_OVERSHOOT = 10;

type Props = {
  collapsed: boolean;
  dragging: boolean;
  previewWidth: number;
  onDragStart: () => void;
  onDragPreview: (width: number) => void;
  onDragCommit: (expand: boolean) => void;
  onToggleCollapse: () => void;
};

function NavIcon({ icon, active }: { icon: string; active: boolean }) {
  return (
    <Icon
      name={icon}
      className={`text-2xl ${active ? "text-primary" : "text-on-surface-variant/60"}`}
    />
  );
}

export default function Sidebar({
  collapsed,
  dragging,
  previewWidth,
  onDragStart,
  onDragPreview,
  onDragCommit,
  onToggleCollapse,
}: Props) {
  const pathname = usePathname();
  const { user } = useAuth();
  const { query, setQuery } = useWorkspaceSearch();
  const dragState = useRef<{ startX: number; fromExpanded: boolean } | null>(null);

  const displayName =
    user && "display_name" in user && user.display_name
      ? user.display_name
      : user && "email" in user && user.email
        ? user.email.split("@")[0]
        : "User";

  const elasticWidth = useCallback((raw: number) => {
    if (raw < SIDEBAR_COLLAPSED_WIDTH) {
      return SIDEBAR_COLLAPSED_WIDTH - Math.min((SIDEBAR_COLLAPSED_WIDTH - raw) * ELASTIC_RESISTANCE, ELASTIC_MAX_OVERSHOOT);
    }
    if (raw > SIDEBAR_EXPANDED_WIDTH) {
      return SIDEBAR_EXPANDED_WIDTH + Math.min((raw - SIDEBAR_EXPANDED_WIDTH) * ELASTIC_RESISTANCE, ELASTIC_MAX_OVERSHOOT);
    }
    return raw;
  }, []);

  const beginDrag = (e: PointerEvent<HTMLDivElement>) => {
    dragState.current = { startX: e.clientX, fromExpanded: !collapsed };
    e.currentTarget.setPointerCapture(e.pointerId);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    onDragStart();
  };

  const moveDrag = (e: PointerEvent<HTMLDivElement>) => {
    const drag = dragState.current;
    if (!drag) return;
    onDragPreview(elasticWidth((drag.fromExpanded ? SIDEBAR_EXPANDED_WIDTH : SIDEBAR_COLLAPSED_WIDTH) + (e.clientX - drag.startX)));
  };

  const endDrag = useCallback(
    (e?: PointerEvent<HTMLDivElement>) => {
      const drag = dragState.current;
      if (!drag) return;
      dragState.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      if (e) {
        const dx = e.clientX - drag.startX;
        const expand = drag.fromExpanded ? dx > -COMMIT_THRESHOLD : dx > COMMIT_THRESHOLD;
        onDragCommit(expand);
      } else {
        onDragCommit(drag.fromExpanded);
      }
    },
    [onDragCommit]
  );

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onToggleCollapse();
    }
  };

  function renderNavItem(item: { label: string; href: string; icon: string; external?: boolean }) {
    const active = !item.external && (pathname === item.href || (item.href !== "/mission-control" && pathname.startsWith(item.href)));
    const classes = `group relative flex items-center border-r-2 transition-all duration-150 ${
      collapsed ? "justify-center py-2 px-0" : "gap-3 py-2 pr-4 pl-3"
    } ${
      active
        ? "border-primary text-primary font-bold"
        : "border-transparent text-on-surface-variant/70 hover:text-primary"
    }`;
    if (item.external) {
      return (
        <a
          key={item.href}
          href={item.href}
          target="_blank"
          rel="noopener noreferrer"
          title={item.label}
          className={classes}
        >
          <NavIcon icon={item.icon} active={active} />
          {!collapsed && <span className="text-body-md whitespace-nowrap">{item.label}</span>}
        </a>
      );
    }
    return (
      <Link
        key={item.href}
        href={item.href}
        title={item.label}
        className={classes}
      >
        <NavIcon icon={item.icon} active={active} />
        {!collapsed && <span className="text-body-md whitespace-nowrap">{item.label}</span>}
      </Link>
    );
  }

  function renderHandle({ label, inset }: { label: string; inset: string }) {
    return (
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={label}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        onPointerDown={beginDrag}
        onPointerMove={moveDrag}
        onPointerUp={endDrag}
        onPointerCancel={() => endDrag()}
        onDoubleClick={onToggleCollapse}
        title="Drag to resize · double-click to collapse"
        className="group flex h-5 shrink-0 cursor-col-resize touch-none items-center outline-none"
      >
        <div
          className={`h-px bg-on-surface-variant/60 transition-colors duration-150 group-hover:bg-on-surface-variant group-focus-visible:bg-primary ${inset}`}
        />
      </div>
    );
  }

  const handleInset = collapsed ? "mx-3 w-auto flex-1" : "mx-6 w-auto flex-1";

  return (
    <aside
      className={`fixed left-0 top-0 z-30 flex h-full flex-col border-r border-outline-variant/10 bg-surface-container-low/95 backdrop-blur-xl ${
        dragging ? "" : "transition-[width] duration-200 ease-out"
      }`}
      style={{ width: previewWidth }}
    >
      {/* Logo + search */}
      <div className={`shrink-0 pt-6 pb-1 ${collapsed ? "px-3" : "px-4"}`}>
        <div className={collapsed ? "flex justify-center" : "px-2"}>
          <span className={`font-serif text-primary tracking-tight leading-none ${collapsed ? "text-headline-md" : "text-headline-sm"}`}>
            {collapsed ? "L" : "Loqi"}
          </span>
        </div>
        {!collapsed && (
          <label className="mt-4 flex items-center gap-2 rounded-lg border border-outline-variant/20 bg-surface-lowest px-3 py-2 transition-colors focus-within:border-primary/50">
            <Icon name="search" className="text-base text-on-surface-variant/50 shrink-0" />
            <input
              type="text"
              aria-label="Search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={(pathname && pageConfig[pathname]?.searchPlaceholder) || "Search..."}
              className="min-w-0 flex-1 bg-transparent text-sm text-on-surface outline-none placeholder:text-on-surface-variant/40"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="Clear search"
                className="shrink-0 text-on-surface-variant/40 hover:text-on-surface transition-colors"
              >
                <Icon name="close" className="text-sm" />
              </button>
            )}
          </label>
        )}
      </div>

      {/* Resize handle */}
      {renderHandle({ label: "Resize sidebar", inset: handleInset })}

      {/* Navigation */}
      <nav className="flex-1 overflow-x-hidden">
        <div className="space-y-0.5 px-4">
          {navigation.map(renderNavItem)}
        </div>

        {renderHandle({ label: "Resize sidebar", inset: `${handleInset} my-3` })}

        <div className="space-y-0.5 px-4">
          {utilityPages.map(renderNavItem)}
        </div>
      </nav>

      {/* Bottom */}
      <div className={`border-t border-outline-variant/10 py-4 shrink-0 ${collapsed ? "px-3" : "px-6"}`}>
        {user && (
          <div className={`flex items-center gap-3 rounded-lg py-2 ${collapsed ? "justify-center px-0" : "px-2"}`}>
            <div className="w-8 h-8 rounded-full bg-surface-container-high flex items-center justify-center text-xs font-bold text-on-surface shrink-0">
              {displayName.charAt(0).toUpperCase()}
            </div>
            {!collapsed && (
              <div className="overflow-hidden">
                <p className="text-xs font-medium text-on-surface truncate">{displayName}</p>
              </div>
            )}
          </div>
        )}
        {!collapsed && (
          <div className="mt-3 flex items-center gap-2 text-[10px] text-on-surface-variant/40">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping-slow rounded-full bg-secondary opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-secondary" />
            </span>
            All Systems Online
          </div>
        )}
      </div>
    </aside>
  );
}
