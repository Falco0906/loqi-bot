"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import Icon from "../shared/Icon";
import { useAuth } from "../../hooks/useAuth";

const navigation = [
  { label: "Mission Control", href: "/mission-control", icon: "dashboard" },
  { label: "Discovery", href: "/discovery", icon: "explore" },
  { label: "Campaigns", href: "/campaigns", icon: "campaign" },
  { label: "Inbox", href: "/inbox", icon: "inbox" },
  { label: "Knowledge", href: "/knowledge", icon: "psychology" },
  { label: "Strategic Update", href: "/strategic-update", icon: "auto_awesome" },
];

const utilityPages = [
  { label: "Settings", href: "/settings", icon: "settings" },
  { label: "Support", href: "/support", icon: "help_outline" },
];

function NavIcon({ icon, active }: { icon: string; active: boolean }) {
  return (
    <Icon
      name={icon}
      className={`text-xl ${active ? "text-primary" : "text-on-surface-variant/60"}`}
    />
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const { user } = useAuth();

  function renderNavItem(item: { label: string; href: string; icon: string }) {
    const active = pathname === item.href || (item.href !== "/mission-control" && pathname.startsWith(item.href));
    return (
      <Link
        key={item.href}
        href={item.href}
        className={`group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-150 ${
          active
            ? "bg-primary-container/15 text-primary"
            : "text-on-surface-variant/70 hover:bg-surface-high/60 hover:text-on-surface"
        }`}
      >
        {active && (
          <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 rounded-full bg-primary" />
        )}
        <NavIcon icon={item.icon} active={active} />
        <span>{item.label}</span>
      </Link>
    );
  }

  return (
    <aside className="fixed left-0 top-0 z-30 flex h-full w-64 flex-col border-r border-outline-variant/10 bg-charcoal/95 backdrop-blur-xl">
      {/* Logo */}
      <div className="flex items-center gap-3 px-6 py-8">
        <div className="flex items-center gap-3">
          <Icon name="rocket_launch" className="text-xl text-primary" />
          <div>
            <div className="text-lg font-serif font-normal text-primary tracking-tight">Loqi AI</div>
            <div className="text-[10px] font-medium uppercase tracking-[0.15em] text-on-surface-variant/40">
              Chief of Staff
            </div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-0.5 px-4">
        {navigation.map(renderNavItem)}

        <div className="my-2 border-t border-outline-variant/10" />

        <div className="space-y-0.5">
          <div className="px-3 py-1">
            <span className="text-[10px] font-medium uppercase tracking-[0.15em] text-on-surface-variant/30">Utilities</span>
          </div>
          {utilityPages.map(renderNavItem)}
        </div>
      </nav>

      {/* Bottom */}
      <div className="border-t border-outline-variant/10 px-6 py-4">
        {user && (
          <div className="flex items-center gap-3 rounded-lg px-2 py-2">
            <div className="w-8 h-8 rounded-full bg-surface-container-high flex items-center justify-center text-xs font-bold text-on-surface">
              {"email" in user && user.email ? user.email[0].toUpperCase() : "L"}
            </div>
            <div className="overflow-hidden">
              <p className="text-xs font-medium text-on-surface truncate">{"email" in user && user.email ? user.email.split("@")[0] : "User"}</p>
              <p className="text-[10px] text-on-surface-variant/50 truncate">Strategic Lead</p>
            </div>
          </div>
        )}
        <div className="mt-3 flex items-center gap-2 text-[10px] text-on-surface-variant/40">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping-slow rounded-full bg-secondary opacity-75" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-secondary" />
          </span>
          All Systems Online
        </div>
      </div>
    </aside>
  );
}
