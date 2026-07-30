"use client";

import { useEffect, useRef } from "react";
import ReactDOM from "react-dom";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  children: React.ReactNode;
}

export default function Drawer({ isOpen, onClose, children }: Props) {
  const drawerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const previousActiveElement = document.activeElement as HTMLElement;
    
    // Focus trap
    const focusableElements = drawerRef.current?.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const firstElement = focusableElements?.[0] as HTMLElement;
    firstElement?.focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      
      if (e.key === "Tab") {
        if (e.shiftKey) {
            if (document.activeElement === firstElement) {
                e.preventDefault();
                (focusableElements?.[focusableElements.length - 1] as HTMLElement)?.focus();
            }
        } else {
            if (document.activeElement === focusableElements?.[focusableElements.length - 1]) {
                e.preventDefault();
                firstElement?.focus();
            }
        }
      }
    };
    
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      previousActiveElement?.focus();
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return ReactDOM.createPortal(
    <div className="fixed inset-0 z-[100] flex justify-end" role="dialog" aria-modal="true">
      <div className="fixed inset-0 bg-obsidian/40 backdrop-blur-sm" onClick={onClose} />
      
      <div 
        ref={drawerRef}
        className="relative w-full max-w-md bg-surface border-l border-outline-variant/20 shadow-glass focus:outline-none"
      >
        {children}
      </div>
    </div>,
    document.body
  );
}
