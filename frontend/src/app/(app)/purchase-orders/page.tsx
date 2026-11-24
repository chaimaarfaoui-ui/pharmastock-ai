"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge, ErrorText, Loading, Modal, PageHeader, Pager, Section, Select, Table, Td, Th, money, num } from "@/components/common";
import { api, post, qs, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useAction, useFetch, useMedicines, useSuppliers } from "@/lib/hooks";

const LIMIT = 20;
const STATUSES = ["", "draft", "approved", "ordered", "partially_received", "completed", "canceled"];

export default function PurchaseOrdersPage() {
  const { user } = useAuth();
  const mgr = user?.role !== "employee";
  const [status, setStatus] = useState(""); const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false); const [open, setOpen] = useState<number | null>(null);
  const list = useFetch(() => api<Page<Row>>(`/purchase-orders${qs({ status, limit: LIMIT, offset })}`), [status, offset]);
  return (
    <div>
      <PageHeader title="Purchase orders" subtitle="Draft → approved → ordered → received. Nothing is ordered automatically: every step is a deliberate, audited action."
        actions={mgr && <Button onClick={() => setCreating(true)}>New purchase order</Button>} />
      <div className="mb-4"><Select value={status} onChange={(v) => { setStatus(v); setOffset(0); }}>{STATUSES.map((s) => <option key={s} value={s}>{s ? s.replace("_", " ") : "All statuses"}</option>)}</Select></div>
      <ErrorText error={list.error} />
      <Section title={`${list.data?.total ?? 0} orders`}>
        {list.loading && !list.data ? <Loading /> : (
          <Table><thead><tr><Th>#</Th><Th>Supplier</Th><Th>Status</Th><Th>Ordered</Th><Th>Expected</Th><Th right>Lines</Th><Th right>Value</Th><Th /></tr></thead>
            <tbody>{list.data?.items.map((p) => (
              <tr key={p.id}><Td>{p.id}</Td><Td>{p.supplier_name}</Td><Td><Badge value={p.status} /></Td><Td>{p.ordered_at ? new Date(p.ordered_at).toLocaleDateString() : "—"}</Td>
                <Td>{p.expected_delivery_date ?? "—"}</Td><Td right>{p.items.length}</Td><Td right>{money(Number(p.total_value))}</Td>
                <Td right><Button size="sm" variant="outline" onClick={() => setOpen(p.id)}>Open</Button></Td></tr>))}</tbody></Table>)}
        <Pager total={list.data?.total ?? 0} limit={LIMIT} offset={offset} onChange={setOffset} />
      </Section>
      {creating && <CreatePO onClose={() => setCreating(false)} onDone={() => { setCreating(false); void list.reload(); }} />}
      {open !== null && <PODetail id={open} mgr={mgr} onClose={() => { setOpen(null); void list.reload(); }} />}
    </div>
  );
}

function CreatePO({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const sups = useSuppliers(); const meds = useMedicines(); const act = useAction();
  const [lines, setLines] = useState<Row[]>([{ medicine_id: "", quantity_ordered: 1, unit_price: 0 }]);
  const set = (i: number, k: string, v: string) => setLines(lines.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget);
    await act.run(async () => {
      await post("/purchase-orders", { supplier_id: Number(f.get("supplier")), expected_delivery_date: f.get("expected") || null, notes: String(f.get("notes") || "") || null,
        items: lines.map((l) => ({ medicine_id: Number(l.medicine_id), quantity_ordered: Number(l.quantity_ordered), unit_price: Number(l.unit_price) })) });
      onDone();
    });
  }
  return (
    <Modal title="New purchase order (draft)" onClose={onClose} wide>
      <form onSubmit={submit} className="grid gap-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block space-y-1.5"><span className="text-sm font-medium">Supplier</span><select name="supplier" required className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm">{sups.data?.items.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
          <Field label="Expected delivery"><Input name="expected" type="date" /></Field>
        </div>
        <Field label="Notes"><Input name="notes" /></Field>
        {lines.map((l, i) => (
          <div key={i} className="flex flex-wrap items-end gap-2">
            <label className="block space-y-1.5"><span className="text-xs font-medium">Medicine</span><select required value={l.medicine_id} onChange={(e) => set(i, "medicine_id", e.target.value)} className="h-10 w-64 rounded-md border border-border bg-background px-3 text-sm"><option value="" disabled>Select…</option>{meds.data?.items.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
            <label className="block space-y-1.5"><span className="text-xs font-medium">Quantity</span><Input type="number" min="1" required className="w-28" value={l.quantity_ordered} onChange={(e) => set(i, "quantity_ordered", e.target.value)} /></label>
            <label className="block space-y-1.5"><span className="text-xs font-medium">Unit price</span><Input type="number" step="0.01" min="0" required className="w-28" value={l.unit_price} onChange={(e) => set(i, "unit_price", e.target.value)} /></label>
            {lines.length > 1 && <Button type="button" variant="ghost" size="sm" onClick={() => setLines(lines.filter((_, j) => j !== i))}>Remove</Button>}
          </div>))}
        <div><Button type="button" variant="outline" size="sm" onClick={() => setLines([...lines, { medicine_id: "", quantity_ordered: 1, unit_price: 0 }])}>Add line</Button></div>
        <ErrorText error={act.error} /><Button type="submit" disabled={act.busy}>Create draft</Button>
      </form>
    </Modal>
  );
}

function PODetail({ id, mgr, onClose }: { id: number; mgr: boolean; onClose: () => void }) {
  const po = useFetch(() => api<Row>(`/purchase-orders/${id}`), [id]);
  const meds = useMedicines(); const act = useAction();
  const names = Object.fromEntries((meds.data?.items ?? []).map((m) => [m.id, m.name]));
  const [recv, setRecv] = useState<Record<number, Row>>({});
  const p = po.data;
  async function step(action: string) { if (await act.run(() => post(`/purchase-orders/${id}/${action}`))) void po.reload(); }
  async function receive() {
    const lines = Object.entries(recv).filter(([, v]) => v.quantity && v.batch_number && v.expiration_date)
      .map(([k, v]) => ({ po_item_id: Number(k), batch_number: v.batch_number, expiration_date: v.expiration_date, quantity: Number(v.quantity) }));
    if (!lines.length) { act.setError("Fill quantity, batch number and expiry for at least one line"); return; }
    if (await act.run(() => post(`/purchase-orders/${id}/receive`, { lines }))) { setRecv({}); void po.reload(); }
  }
  const setR = (i: number, k: string, v: string) => setRecv({ ...recv, [i]: { ...recv[i], [k]: v } });
  return (
    <Modal title={`Purchase order #${id}`} onClose={onClose} wide>
      <ErrorText error={po.error ?? act.error} />
      {!p ? <Loading /> : (<>
        <div className="mb-3 flex flex-wrap items-center gap-3 text-sm"><Badge value={p.status} /><span>{p.supplier_name}</span><span className="text-muted-foreground">Total {money(Number(p.total_value))}</span></div>
        <Table><thead><tr><Th>Medicine</Th><Th right>Ordered</Th><Th right>Received</Th><Th right>Unit price</Th>{["ordered", "partially_received"].includes(p.status) && <><Th>Receive now</Th><Th>Batch no.</Th><Th>Expiry</Th></>}</tr></thead>
          <tbody>{p.items.map((it: Row) => (
            <tr key={it.id}><Td>{names[it.medicine_id] ?? it.medicine_id}</Td><Td right>{num(it.quantity_ordered)}</Td><Td right>{num(it.quantity_received)}</Td><Td right>{money(Number(it.unit_price))}</Td>
              {["ordered", "partially_received"].includes(p.status) && it.quantity_received < it.quantity_ordered && <>
                <Td><Input type="number" min="1" max={it.quantity_ordered - it.quantity_received} className="h-8 w-24" value={recv[it.id]?.quantity ?? ""} onChange={(e) => setR(it.id, "quantity", e.target.value)} aria-label="Quantity received" /></Td>
                <Td><Input className="h-8 w-32" value={recv[it.id]?.batch_number ?? ""} onChange={(e) => setR(it.id, "batch_number", e.target.value)} aria-label="Batch number" /></Td>
                <Td><Input type="date" className="h-8" value={recv[it.id]?.expiration_date ?? ""} onChange={(e) => setR(it.id, "expiration_date", e.target.value)} aria-label="Expiry date" /></Td></>}
            </tr>))}</tbody></Table>
        <div className="mt-4 flex flex-wrap gap-2">
          {mgr && p.status === "draft" && <Button onClick={() => step("approve")} disabled={act.busy}>Approve</Button>}
          {mgr && p.status === "approved" && <Button onClick={() => step("order")} disabled={act.busy}>Mark as ordered (placed with supplier)</Button>}
          {["ordered", "partially_received"].includes(p.status) && <Button onClick={receive} disabled={act.busy}>Record delivery</Button>}
          {mgr && ["draft", "approved", "ordered"].includes(p.status) && <Button variant="destructive" onClick={() => window.confirm("Cancel this purchase order?") && step("cancel")} disabled={act.busy}>Cancel order</Button>}
        </div>
      </>)}
    </Modal>
  );
}
