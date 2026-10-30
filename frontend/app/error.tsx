"use client";

export default function Error({ reset }: { reset: () => void }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
      <div className="max-w-md rounded-3xl border border-slate-200 bg-white p-8 text-center shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-orange-600">Error</p>
        <h1 className="mt-4 text-3xl font-bold text-slate-900">Something went wrong</h1>
        <p className="mt-3 text-slate-600">The app could not load the requested state.</p>
        <button
          type="button"
          onClick={() => reset()}
          className="mt-6 inline-flex rounded-full bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800"
        >
          Try again
        </button>
      </div>
    </main>
  );
}
