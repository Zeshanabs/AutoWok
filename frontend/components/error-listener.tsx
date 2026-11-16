"use client";

import { useEffect } from "react";

import { reportClientError } from "@/lib/error-reporting";

/** Reports uncaught browser errors and unhandled promise rejections. Renders nothing. */
export function ErrorListener() {
  useEffect(() => {
    const onError = (event: ErrorEvent) =>
      reportClientError({ message: event.message || "Unknown error", stack: event.error instanceof Error ? event.error.stack : undefined, source: "window-error" });
    const onRejection = (event: PromiseRejectionEvent) => {
      const reason: unknown = event.reason;
      reportClientError({
        message: reason instanceof Error ? reason.message : String(reason ?? "Unhandled rejection"),
        stack: reason instanceof Error ? reason.stack : undefined,
        source: "unhandled-rejection",
      });
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);
  return null;
}
