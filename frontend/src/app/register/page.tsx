"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthShell } from "@/components/auth-form-shell";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { auth } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function RegisterPage() {
  const router = useRouter();
  const { refreshUser } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true); setError(null);
    try {
      await auth.register({
        pharmacy_name: String(f.get("pharmacy_name")), full_name: String(f.get("full_name")),
        email: String(f.get("email")), password: String(f.get("password")),
      });
      await refreshUser();
      router.replace("/dashboard");
    } catch (err) { setError(err instanceof Error ? err.message : "Registration failed"); }
    finally { setBusy(false); }
  }

  return (
    <AuthShell title="Register your pharmacy" subtitle="You will be the administrator and can invite your team afterwards.">
      <form onSubmit={onSubmit} className="space-y-4">
        <Field label="Pharmacy name"><Input name="pharmacy_name" required minLength={2} /></Field>
        <Field label="Your full name"><Input name="full_name" autoComplete="name" required minLength={2} /></Field>
        <Field label="Email"><Input name="email" type="email" autoComplete="email" required /></Field>
        <Field label="Password (min. 10 characters)"><Input name="password" type="password" autoComplete="new-password" required minLength={10} /></Field>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <Button type="submit" className="w-full" disabled={busy}>{busy ? "Creating…" : "Create account"}</Button>
        <p className="text-center text-sm text-muted-foreground">
          Already registered? <Link href="/login" className="font-medium text-primary underline">Sign in</Link>
        </p>
      </form>
    </AuthShell>
  );
}
