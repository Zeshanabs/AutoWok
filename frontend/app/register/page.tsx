"use client";

import { RegisterForm } from "@/components/auth-forms";
import { AuthLayout } from "@/components/auth-layout";
import { GuestPage } from "@/components/route-guards";

export default function RegisterPage() {
  return (
    <GuestPage>
      <AuthLayout title="Create your account" description="Your account includes a private personal workspace.">
        <RegisterForm />
      </AuthLayout>
    </GuestPage>
  );
}
