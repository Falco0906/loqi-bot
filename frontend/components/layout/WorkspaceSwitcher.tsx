"use client";

import { useState } from "react";
import Icon from "../shared/Icon";

export default function WorkspaceSwitcher() {
  const [isOpen, setIsOpen] = useState(false);
  
  return (
    <div className="relative">
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 rounded-lg px-3 py-1.5 hover:bg-surface-high/80 transition-all"
      >
        <div className="flex h-6 w-6 items-center justify-center rounded bg-primary-container text-[10px] font-bold text-on-primary">
          L
        </div>
        <span className="text-sm font-medium text-on-surface">Loqi HQ</span>
        <Icon name="expand_more" className="text-outline text-lg" />
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 mt-2 w-48 rounded-container bg-surface-high border border-outline-variant/20 shadow-glass">
            <div className="p-2 text-sm text-outline">Switch Workspace</div>
        </div>
      )}
    </div>
  );
}