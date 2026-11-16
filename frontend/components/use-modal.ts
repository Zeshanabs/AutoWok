"use client";

import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

type Options = {
  /** Element to focus when the dialog opens. Defaults to the first focusable element. */
  initialFocus?: RefObject<HTMLElement | null>;
  /** When false, Escape does not close the dialog (for example while a request is running). */
  canClose?: boolean;
};

/**
 * Keyboard behaviour for a modal dialog: moves focus in when it opens, keeps
 * Tab inside it, closes on Escape, and returns focus to the element that
 * opened it. Focus only moves when `open` changes, never on re-render.
 */
export function useModal<T extends HTMLElement>(open: boolean, onClose: () => void, options: Options = {}) {
  const containerRef = useRef<T>(null);
  const onCloseRef = useRef(onClose);
  const canCloseRef = useRef(options.canClose ?? true);
  const initialFocusRef = useRef(options.initialFocus);

  useEffect(() => {
    onCloseRef.current = onClose;
    canCloseRef.current = options.canClose ?? true;
    initialFocusRef.current = options.initialFocus;
  });

  useEffect(() => {
    if (!open) return;
    const container = containerRef.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const first = initialFocusRef.current?.current ?? container?.querySelector<HTMLElement>(FOCUSABLE) ?? container;
    first?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (canCloseRef.current) {
          event.stopPropagation();
          onCloseRef.current();
        }
        return;
      }
      if (event.key !== "Tab" || !container) return;
      const items = Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) {
        event.preventDefault();
        container.focus();
        return;
      }
      const firstItem = items[0];
      const lastItem = items[items.length - 1];
      const active = document.activeElement;
      if (!container.contains(active)) {
        event.preventDefault();
        firstItem.focus();
      } else if (event.shiftKey && active === firstItem) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && active === lastItem) {
        event.preventDefault();
        firstItem.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (opener && document.contains(opener)) opener.focus();
    };
  }, [open]);

  return containerRef;
}
