"use client";

import { useCallback, useEffect, useRef } from "react";

const EASE_ELASTIC = (t: number) => 1 - Math.pow(1 - t, 4);

export function getScrollParent(el: HTMLElement | null): HTMLElement | null {
  let node = el?.parentElement ?? null;
  while (node) {
    const style = getComputedStyle(node);
    if (/(auto|scroll|overlay)/.test(style.overflowY)) return node;
    node = node.parentElement;
  }
  return document.documentElement;
}

export function useGuidedScroll<T extends HTMLElement>(targetRef: React.RefObject<T | null>) {
  const rafRef = useRef<number | null>(null);
  const interruptedRef = useRef(false);

  const cancel = useCallback(() => {
    interruptedRef.current = true;
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  const scrollToSection = useCallback(
    (el: HTMLElement, opts?: { duration?: number; offset?: number }) => {
      const scroller = getScrollParent(targetRef.current);
      if (!scroller || !el) return;

      interruptedRef.current = false;
      cancelAnimationFrame(rafRef.current ?? 0);
      rafRef.current = null;

      const duration = opts?.duration ?? 1100;
      const offset = opts?.offset ?? 48;
      const startY = scroller.scrollTop;
      const endY = Math.max(0, el.getBoundingClientRect().top + scroller.scrollTop - offset);
      const distance = endY - startY;

      if (Math.abs(distance) < 2) return;

      const start = performance.now();
      const step = (now: number) => {
        if (interruptedRef.current) return;
        const t = Math.min(1, (now - start) / duration);
        scroller.scrollTop = startY + distance * EASE_ELASTIC(t);
        if (t < 1) {
          rafRef.current = requestAnimationFrame(step);
        } else {
          rafRef.current = null;
        }
      };
      rafRef.current = requestAnimationFrame(step);
    },
    [targetRef]
  );

  useEffect(() => {
    const scroller = getScrollParent(targetRef.current);
    if (!scroller) return;

    const onInterrupt = () => cancel();
    scroller.addEventListener("wheel", onInterrupt, { passive: true });
    scroller.addEventListener("touchstart", onInterrupt, { passive: true });
    scroller.addEventListener("keydown", onInterrupt);
    return () => {
      scroller.removeEventListener("wheel", onInterrupt);
      scroller.removeEventListener("touchstart", onInterrupt);
      scroller.removeEventListener("keydown", onInterrupt);
    };
  }, [targetRef, cancel]);

  useEffect(() => () => cancel(), [cancel]);

  return { scrollToSection, cancel };
}
