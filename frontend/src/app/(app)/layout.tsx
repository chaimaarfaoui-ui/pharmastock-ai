"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Bell, LogOut, Menu, Pill, X } from "lucide-react";
import { api, type Row } from "@/lib/api";
import { useFetch } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth-context";
import { NAV } from "@/lib/nav";
import { cn } from "@/lib/utils";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const settings = useFetch(() => api<Row>("/settings"), [user?.id]);
  const notes = useFetch(() => api<Row>("/notifications?status=unread&limit=1"), [pathname, user?.id]);

  useEffect(() => { if (!loading && !user) router.replace("/login"); }, [loading, user, router]);
  useEffect(() => setOpen(false), [pathname]);

  if (loading || !user) {
    return <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">Loading…</div>;
  }

  // Client-side filtering is a UX convenience only; the API enforces permissions on every request.
  const items = NAV.filter((n) => n.roles.includes(user.role));
  const current = items.find((n) => pathname.startsWith(n.href));

  return (
    <div className="min-h-screen md:grid md:grid-cols-[15rem_1fr]">
      <aside className={cn("fixed inset-y-0 left-0 z-30 w-60 border-r border-border bg-background p-4 transition-transform md:static md:translate-x-0", open ? "translate-x-0" : "-translate-x-full")}>
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-2 font-semibold"><Pill className="h-5 w-5 text-primary" aria-hidden />PharmaStock AI</div>
          <Button variant="ghost" size="sm" className="md:hidden" onClick={() => setOpen(false)} aria-label="Close menu"><X className="h-4 w-4" /></Button>
        </div>
        <nav aria-label="Main" className="space-y-1">
          {items.map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} aria-current={pathname.startsWith(href) ? "page" : undefined}
              className={cn("flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium hover:bg-muted", pathname.startsWith(href) && "bg-muted text-primary")}>
              <Icon className="h-4 w-4" aria-hidden />{label}
            </Link>
          ))}
        </nav>
      </aside>
      {open && <div className="fixed inset-0 z-20 bg-black/40 md:hidden" onClick={() => setOpen(false)} aria-hidden />}
      <div className="flex min-w-0 flex-col">
        {settings.data?.data_source === "synthetic" && (
          <div role="status" className="bg-amber-500/20 px-4 py-1.5 text-center text-xs font-medium text-amber-900 dark:text-amber-200">Synthetic demonstration data. Nothing here is real pharmacy data or real operational results.</div>
        )}
        <header className="flex h-14 items-center justify-between border-b border-border px-4">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" className="md:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-4 w-4" /></Button>
            <span className="text-sm font-medium">{current?.label}</span>
          </div>
          <div className="flex items-center gap-3">
            <Link href="/notifications" aria-label="Notifications" className="relative rounded-md p-2 hover:bg-muted"><Bell className="h-4 w-4" />{(notes.data?.unread ?? 0) > 0 && <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-destructive px-1 text-center text-[10px] text-white">{notes.data?.unread}</span>}</Link>
            <div className="hidden text-right text-xs sm:block">
              <div className="font-medium">{user.full_name}</div>
              <div className="capitalize text-muted-foreground">{user.role}</div>
            </div>
            <Button variant="outline" size="sm" onClick={() => { logout(); router.replace("/login"); }}><LogOut className="h-4 w-4" aria-hidden />Sign out</Button>
          </div>
        </header>
        <main className="flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
