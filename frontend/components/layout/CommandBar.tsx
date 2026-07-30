"use client";

import { useState, useEffect } from "react";

type Props = {
  isOpen: boolean;
  onClose: () => void;
};

export default function CommandBar({ isOpen, onClose }: Props) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        isOpen ? onClose() : null; // Need a way to open it too
      }
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-24 bg-obsidian/60 backdrop-blur-sm" onClick={onClose}>
      <div 
        className="w-full max-w-lg rounded-container border border-outline-variant/30 bg-surface shadow-glass animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b border-outline-variant/10">
          <input 
            type="text" 
            placeholder="Search commands..." 
            className="w-full bg-transparent text-lg text-on-surface outline-none"
            autoFocus
          />
        </div>
        <div className="p-4 text-sm text-outline">
            Future commands will appear here.
        </div>
      </div>
    </div>
  );
}