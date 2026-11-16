"use client";

import { useEffect } from "react";

import { reportClientError } from "@/lib/error-reporting";

/** Last-resort boundary for errors thrown by the root layout itself. */
export default function GlobalError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    reportClientError({ message: error.message, stack: error.stack, digest: error.digest, source: "error-boundary" });
  }, [error]);

  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", padding: "3rem", color: "#0f172a" }}>
        <title>Something went wrong · Autowok</title>
        <main role="alert">
          <h1>Something went wrong</h1>
          <p>Autowok could not be displayed. Your work on the server is not affected.</p>
          <button type="button" onClick={() => retry()} style={{ padding: "0.6rem 1.2rem", marginTop: "1rem" }}>
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
