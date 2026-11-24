"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge, ErrorText, Loading, Modal, PageHeader, Pager, Section, Select, Table, Td, Th, money, num } from "@/components/common";
import { api, post, qs, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useAction, useFetch, useMedicines, useSuppliers } from "@/lib/hooks";

const LIMIT = 25;
type Op = { kind: "write-offs" | "adjustments" | "returns/customer" | "returns/supplier"; batch: Row } | "receive" | null;

export default function BatchesPage() {
  const { user } = useAuth();
  const mgr = user?.role !== "employee";
  const [med, setMed] = useState(""); const [within, setWithin] = useState(""); const [empty, setEmpty] = useState(false); const [offset, setOffset] = useState(0);
  const [op, setOp] = useState<Op>(null);
  const meds = useMedicines();
  const list = useFetch(() => api<Page<Row>>(`/batches${qs({ medicine_id: med, expiring_within_days: within, include_empty: empty, limit: LIMIT, offset })}`), [med, within, empty, offset]);

  return (
    <div>
      <PageHeader title="Batches" subtitle="Stock is held per batch (FEFO: the earliest-expiring usable batch is dispensed first). Every change is recorded in the movement ledger."
        actions={<Button onClick={() => setOp("receive")}>Receive stock</Button>} />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Select value={med} onChange={(v) => { setMed(v); setOffset(0); }}><option value="">All medicines</option>{meds.data?.items.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select>
        <Select value={within} onChange={(v) => { setWithin(v); setOffset(0); }}><option value="">Any expiry</option><option value="30">Expiring ≤ 30 days</option><option value="60">Expiring ≤ 60 days</option><option value="90">Expiring ≤ 90 days</option></Select>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={empty} onChange={(e) => { setEmpty(e.target.checked); setOffset(0); }} />Include empty batches</label>
      </div>
      <ErrorText error={list.error} />
      <Section title={`${list.data?.total ?? 0} batches`}>
        {list.loading && !list.data ? <Loading /> : (
          <Table>
            <thead><tr><Th>Medicine</Th><Th>Batch</Th><Th>Expires</Th><Th right>Days left</Th><Th right>Remaining / received</Th><Th right>Value</Th><Th>Actions</Th></tr></thead>
            <tbody>{list.data?.items.map((b) => (
              <tr key={b.id}>
                <Td>{b.medicine_name}</Td><Td>{b.batch_number}</Td><Td>{b.expiration_date} {b.is_expired && <Badge value="expired" />}</Td>
                <Td right>{b.days_to_expiry}</Td><Td right>{num(b.quantity_remaining)} / {num(b.quantity_received)}</Td><Td right>{money(Number(b.remaining_value))}</Td>
                <Td><div className="flex flex-wrap gap-1">
                  {!b.is_expired && <Button size="sm" variant="outline" onClick={() => setOp({ kind: "returns/customer", batch: b })}>Customer return</Button>}
                  {mgr && <><Button size="sm" variant="outline" onClick={() => setOp({ kind: "adjustments", batch: b })}>Adjust count</Button>
                    <Button size="sm" variant="outline" onClick={() => setOp({ kind: "returns/supplier", batch: b })}>Return to supplier</Button>
                    <Button size="sm" variant="destructive" onClick={() => setOp({ kind: "write-offs", batch: b })}>Write off</Button></>}
                </div></Td>
              </tr>))}</tbody>
          </Table>)}
        <Pager total={list.data?.total ?? 0} limit={LIMIT} offset={offset} onChange={setOffset} />
      </Section>
      {op === "receive" && <ReceiveForm onClose={() => setOp(null)} onDone={() => { setOp(null); void list.reload(); }} />}
      {op && op !== "receive" && <BatchOp op={op} onClose={() => setOp(null)} onDone={() => { setOp(null); void list.reload(); }} />}
      <p className="mt-2 text-xs text-muted-foreground">Expired stock is never sold or redistributed by the system: use a write-off. Returns to a supplier are recorded only; confirm legal and operational eligibility yourself.</p>
    </div>
  );
}

function ReceiveForm({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const meds = useMedicines(); const sups = useSuppliers(); const act = useAction();
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    await act.run(async () => {
      await post("/inventory/receipts", { medicine_id: Number(f.get("medicine")), batch_number: String(f.get("batch")), expiration_date: String(f.get("expiry")),
        quantity: Number(f.get("qty")), unit_cost: Number(f.get("cost")), supplier_id: f.get("supplier") ? Number(f.get("supplier")) : null });
      onDone();
    });
  }
  return (
    <Modal title="Receive stock (new batch)" onClose={onClose}>
      <form onSubmit={submit} className="grid gap-3">
        <label className="block space-y-1.5"><span className="text-sm font-medium">Medicine</span><select name="medicine" required className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm">{meds.data?.items.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
        <Field label="Batch number"><Input name="batch" required /></Field>
        <Field label="Expiration date"><Input name="expiry" type="date" required /></Field>
        <Field label="Quantity received"><Input name="qty" type="number" min="1" required /></Field>
        <Field label="Unit cost"><Input name="cost" type="number" step="0.01" min="0" required /></Field>
        <label className="block space-y-1.5"><span className="text-sm font-medium">Supplier (optional)</span><select name="supplier" className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"><option value="">None</option>{sups.data?.items.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <ErrorText error={act.error} /><Button type="submit" disabled={act.busy}>{act.busy ? "Saving…" : "Receive"}</Button>
      </form>
    </Modal>
  );
}

function BatchOp({ op, onClose, onDone }: { op: Exclude<Op, "receive" | null>; onClose: () => void; onDone: () => void }) {
  const act = useAction(); const b = op.batch;
  const titles = { "write-offs": "Write off stock", adjustments: "Adjust to counted quantity", "returns/customer": "Customer return (restock)", "returns/supplier": "Return to supplier" } as const;
  const isAdjust = op.kind === "adjustments", reasonRequired = op.kind !== "returns/customer";
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    await act.run(async () => {
      const reason = String(f.get("reason") ?? "");
      await post(`/inventory/${op.kind}`, isAdjust ? { batch_id: b.id, new_quantity: Number(f.get("qty")), reason } : { batch_id: b.id, quantity: Number(f.get("qty")), reason: reason || null });
      onDone();
    });
  }
  return (
    <Modal title={titles[op.kind]} onClose={onClose}>
      <p className="mb-3 text-sm text-muted-foreground">{b.medicine_name} · batch {b.batch_number} · {num(b.quantity_remaining)} units on hand</p>
      <form onSubmit={submit} className="grid gap-3">
        <Field label={isAdjust ? "Counted quantity" : "Quantity"}><Input name="qty" type="number" min={isAdjust ? 0 : 1} required /></Field>
        <Field label={reasonRequired ? "Reason (required)" : "Reason (optional)"}><Input name="reason" required={reasonRequired} minLength={reasonRequired ? 3 : undefined} /></Field>
        <ErrorText error={act.error} /><Button type="submit" disabled={act.busy}>{act.busy ? "Saving…" : "Confirm"}</Button>
      </form>
    </Modal>
  );
}
