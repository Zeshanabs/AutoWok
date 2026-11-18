export default function Loading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 text-slate-600">
      <p role="status" className="flex items-center gap-3 text-sm font-medium">
        <span aria-hidden="true" className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-600" />
        Loading Autowok…
      </p>
    </div>
  );
}
