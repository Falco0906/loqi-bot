"use client";

import { useEffect, useRef } from "react";
import { getScrollParent } from "./useGuidedScroll";

export function useRevealOnScroll<T extends HTMLElement>(containerRef: React.RefObject<T | null>) {
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const targets = Array.from(container.querySelectorAll<HTMLElement>(".reveal"));
    if (targets.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        }
      },
      { root: getScrollParent(container), rootMargin: "0px 0px -12% 0px", threshold: 0.05 }
    );

    targets.forEach((t) => observer.observe(t));
    observerRef.current = observer;

    return () => {
      observer.disconnect();
      observerRef.current = null;
    };
  }, [containerRef]);

  return observerRef;
}
