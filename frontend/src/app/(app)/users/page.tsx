"use client";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { users, type Role, type User } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function UsersPage() {
  const { user: me } = useAuth();
  const [list, setList] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setList(await users.list()); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load users"); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  if (me && me.role !== "admin") return <p className="text-sm">Only administrators can manage users.</p>;

  async function onCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    setBusy(true); setError(null);
    try {
      await users.create({ full_name: String(f.get("full_name")), email: String(f.get("email")),
        password: String(f.get("password")), role: String(f.get("role")) as Role });
      form.reset(); await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not create user"); }
    finally { setBusy(false); }
  }

  async function onDeactivate(u: User) {
    if (!window.confirm(`Deactivate ${u.full_name}? They will lose access immediately.`)) return;
    try { await users.deactivate(u.id); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not deactivate user"); }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <h1 className="text-2xl font-semibold">Users</h1>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <Card>
        <CardHeader><CardTitle>Team members</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border text-muted-foreground">
              <tr><th className="py-2 pr-4 font-medium">Name</th><th className="pr-4 font-medium">Email</th><th className="pr-4 font-medium">Role</th><th className="pr-4 font-medium">Status</th><th /></tr>
            </thead>
            <tbody>
              {list.map((u) => (
                <tr key={u.id} className="border-b border-border last:border-0">
                  <td className="py-2 pr-4">{u.full_name}</td><td className="pr-4">{u.email}</td>
                  <td className="pr-4 capitalize">{u.role}</td>
                  <td className="pr-4">{u.is_active ? "Active" : "Deactivated"}</td>
                  <td className="text-right">
                    {u.is_active && u.id !== me?.id && <Button variant="destructive" size="sm" onClick={() => onDeactivate(u)}>Deactivate</Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Add a user</CardTitle></CardHeader>
        <CardContent>
          <form onSubmit={onCreate} className="grid gap-4 sm:grid-cols-2">
            <Field label="Full name"><Input name="full_name" required minLength={2} /></Field>
            <Field label="Email"><Input name="email" type="email" required /></Field>
            <Field label="Temporary password (min. 10 characters)"><Input name="password" type="password" required minLength={10} autoComplete="new-password" /></Field>
            <Field label="Role">
              <select name="role" defaultValue="employee" className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm">
                <option value="employee">Inventory employee</option>
                <option value="manager">Pharmacist / manager</option>
                <option value="admin">Administrator</option>
              </select>
            </Field>
            <div className="sm:col-span-2"><Button type="submit" disabled={busy}>{busy ? "Adding…" : "Add user"}</Button></div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
