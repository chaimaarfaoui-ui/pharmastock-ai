"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthShell } from "@/components/auth-form-shell";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { auth } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function LoginPage() {
  const router = useRouter();
  const { refreshUser } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true); setError(null);
    try {
      await auth.login(String(f.get("email")), String(f.get("password")));
      await refreshUser();
      router.replace("/dashboard");
    } catch (err) { setError(err instanceof Error ? err.message : "Login failed"); }
    finally { setBusy(false); }
  }

  return (
    <AuthShell title="Sign in" subtitle="Access your pharmacy's inventory workspace.">
      <form onSubmit={onSubmit} className="space-y-4">
        <Field label="Email"><Input name="email" type="email" autoComplete="email" required /></Field>
        <Field label="Password"><Input name="password" type="password" autoComplete="current-password" required /></Field>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <Button type="submit" className="w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</Button>
        <p className="text-center text-sm text-muted-foreground">
          New pharmacy? <Link href="/register" className="font-medium text-primary underline">Create an account</Link>
        </p>
      </form>
    </AuthShell>
  );
}
