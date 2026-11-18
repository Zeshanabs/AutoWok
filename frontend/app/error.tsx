"use client";

import { useEffect } from "react";

import { reportClientError } from "@/lib/error-reporting";

export default function Error({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    reportClientError({ message: error.message, stack: error.stack, digest: error.digest, source: "error-boundary" });
  }, [error]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
      <div role="alert" className="max-w-md text-center">
        <h1 className="text-3xl font-bold text-slate-900">Something went wrong</h1>
        <p className="mt-3 text-slate-600">This page could not be loaded. Try again; if it keeps happening, reload the browser tab.</p>
        <button
          type="button"
          onClick={() => retry()}
          className="mt-6 inline-flex rounded-xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white hover:bg-indigo-700"
        >
          Try again
        </button>
      </div>
    </main>
  );
}
