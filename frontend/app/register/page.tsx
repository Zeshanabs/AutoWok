"use client";

import Link from "next/link";

import { RegisterForm } from "@/components/auth-forms";
import { GuestPage } from "@/components/route-guards";

export default function RegisterPage() {
  return (
    <GuestPage>
      <main className="flex min-h-screen items-center justify-center bg-slate-50 px-5 py-12">
        <section className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
          <Link href="/" className="text-sm font-semibold text-indigo-700">
            ← Autowok
          </Link>
          <h1 className="mt-7 text-3xl font-bold tracking-tight">
            Create your account
          </h1>
          <p className="mb-7 mt-2 text-sm text-slate-600">
            Your account includes a private personal workspace.
          </p>
          <RegisterForm />
        </section>
      </main>
    </GuestPage>
  );
}
