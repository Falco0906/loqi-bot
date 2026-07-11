"use client";

import { useEffect, useState } from "react";
import Icon from "./Icon";

type ToastType = "success" | "error" | "info";

type ToastItem = {
  id: string;
  type: ToastType;
  message: string;
};

let addToastFn: ((type: ToastType, message: string) => void) | null = null;

export function toast(type: ToastType, message: string) {
  addToastFn?.(type, message);
}

const config = {
  success: { icon: "check_circle", bg: "bg-secondary/10", border: "border-secondary/30", text: "text-secondary" },
  error: { icon: "error", bg: "bg-error/10", border: "border-error/30", text: "text-error" },
  info: { icon: "info", bg: "bg-primary/10", border: "border-primary/30", text: "text-primary" },
};

export default function ToastContainer() {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    addToastFn = (type, message) => {
      const id = crypto.randomUUID();
      setItems((prev) => [...prev, { id, type, message }]);
      setTimeout(() => {
        setItems((prev) => prev.filter((t) => t.id !== id));
      }, 3500);
    };
    return () => { addToastFn = null; };
  }, []);

  if (items.length === 0) return null;

  return (
    <div className="fixed bottom-20 right-6 z-50 flex flex-col gap-2 pointer-events-none">
      {items.map((item) => {
        const c = config[item.type];
        return (
          <div
            key={item.id}
            className={`pointer-events-auto flex items-center gap-2.5 rounded-xl border ${c.border} ${c.bg} px-4 py-3 shadow-lg animate-slide-up max-w-sm`}
          >
            <Icon name={c.icon} className={`text-sm shrink-0 ${c.text}`} />
            <span className="text-label-sm text-on-surface font-medium">{item.message}</span>
          </div>
        );
      })}
    </div>
  );
}
