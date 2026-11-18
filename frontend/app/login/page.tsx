"use client";

import { LoginForm } from "@/components/auth-forms";
import { AuthLayout } from "@/components/auth-layout";
import { GuestPage } from "@/components/route-guards";

export default function LoginPage() {
  return (
    <GuestPage>
      <AuthLayout title="Welcome back" description="Sign in to your Autowok workspace.">
        <LoginForm />
      </AuthLayout>
    </GuestPage>
  );
}
