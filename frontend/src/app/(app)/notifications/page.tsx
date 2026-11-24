"use client";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge, Empty, ErrorText, Loading, PageHeader, Section, Select } from "@/components/common";
import { api, patch, post, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useAction, useFetch } from "@/lib/hooks";

const LINK: Record<string, string> = { shortage_alert: "/shortage", expiration_alert: "/expiration", reorder_recommendation: "/reorder" };

export default function NotificationsPage() {
  const { user } = useAuth();
  const [status, setStatus] = useState("");
  const list = useFetch(() => api<Row>(`/notifications${status ? `?status=${status}` : ""}`), [status]); const act = useAction();
  async function set(id: number, s: string) { if (await act.run(() => patch(`/notifications/${id}`, { status: s }))) void list.reload(); }
  async function readAll() { if (await act.run(() => post("/notifications/read-all"))) void list.reload(); }
  return (
    <div>
      <PageHeader title="Notifications" subtitle="Events from shortage, expiration and reorder analyses. Mark items reviewed or resolved; history is kept for auditing." actions={<Button variant="outline" onClick={readAll} disabled={act.busy}>Mark all read</Button>} />
      <ErrorText error={list.error ?? act.error} />
      <div className="mb-4"><Select value={status} onChange={setStatus}><option value="">All</option><option value="unread">Unread</option><option value="read">Read</option><option value="resolved">Resolved</option></Select></div>
      <Section title={`${list.data?.items.length ?? 0} notifications`}>
        {list.loading && !list.data ? <Loading /> : !list.data?.items.length ? <Empty>Nothing here.</Empty> : (
          <ul className="divide-y divide-border">{list.data.items.map((n: Row) => (
            <li key={n.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
              <div className="max-w-2xl"><div className="flex items-center gap-2"><Badge value={n.severity} />{n.status === "unread" && <span className="text-xs font-semibold text-primary">NEW</span>}<span className="font-medium">{n.title}</span></div>
                {n.body && <p className="mt-1 text-sm text-muted-foreground">{n.body}</p>}<p className="mt-1 text-xs text-muted-foreground">{new Date(n.created_at).toLocaleString()} · {n.status}</p></div>
              <div className="flex gap-1">{LINK[n.entity_type] && user?.role !== "employee" && <Link href={LINK[n.entity_type]} className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted">Open</Link>}
                {n.status === "unread" && <Button size="sm" variant="outline" onClick={() => set(n.id, "read")}>Mark read</Button>}{n.status !== "resolved" && <Button size="sm" variant="outline" onClick={() => set(n.id, "resolved")}>Resolve</Button>}</div>
            </li>))}</ul>)}
      </Section>
    </div>
  );
}
