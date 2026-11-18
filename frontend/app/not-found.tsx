import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
      <div className="max-w-md text-center">
        <p className="font-display text-7xl font-extrabold text-slate-300">404</p>
        <h1 className="mt-4 text-3xl font-bold text-slate-900">Page not found</h1>
        <p className="mt-3 text-slate-600">This address does not match a page in Autowok. It may have been moved or deleted.</p>
        <Link href="/dashboard" className="mt-6 inline-flex rounded-xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white hover:bg-indigo-700">
          Go to the dashboard
        </Link>
      </div>
    </main>
  );
}
