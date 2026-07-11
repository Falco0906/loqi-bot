"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import Icon from "../shared/Icon";

const navItems = [
  { label: "Mission Control", href: "/mission-control", icon: "dashboard" },
  { label: "Discovery", href: "/discovery", icon: "explore" },
  { label: "Campaigns", href: "/campaigns", icon: "campaign" },
  { label: "Campaign Intelligence", href: "/campaign-intelligence", icon: "insights" },
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

  return (
    <aside className="fixed left-0 top-0 z-30 flex h-full w-64 flex-col border-r border-outline-variant/10 bg-charcoal/95 backdrop-blur-xl">
      {/* Logo */}
      <div className="flex items-center gap-3 border-b border-outline-variant/10 px-5 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-container/20">
          <Icon name="rocket_launch" className="text-lg text-primary" />
        </div>
        <div>
          <div className="text-sm font-semibold text-on-surface tracking-tight">Loqi</div>
          <div className="text-[10px] font-medium uppercase tracking-[0.2em] text-on-surface-variant/40">
            Outbound OS
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-0.5 px-3 py-4">
        {navItems.map((item) => {
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
        })}
      </nav>

      {/* Bottom */}
      <div className="border-t border-outline-variant/10 px-4 py-4">
        <div className="flex items-center gap-2 rounded-lg px-2 py-2 text-xs text-on-surface-variant/50">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping-slow rounded-full bg-secondary opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-secondary" />
          </span>
          All Systems Online
        </div>
      </div>
    </aside>
  );
}
