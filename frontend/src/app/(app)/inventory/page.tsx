"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { ErrorText, Loading, PageHeader, Pager, Section, Select, Stat, Table, Td, Th, num } from "@/components/common";
import { api, post, qs, type Page, type Row } from "@/lib/api";
import { useAction, useFetch, useMedicines } from "@/lib/hooks";

const LIMIT = 25;
const TYPES = ["", "receipt", "sale", "dispense", "return_in", "return_out", "adjustment", "write_off"];

export default function InventoryPage() {
  const meds = useMedicines(); const act = useAction();
  const [type, setType] = useState(""); const [med, setMed] = useState(""); const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<Row | null>(null);
  const moves = useFetch(() => api<Page<Row>>(`/inventory/movements${qs({ movement_type: type, medicine_id: med, limit: LIMIT, offset })}`), [type, med, offset]);
  const low = useFetch(() => api<Page<Row>>("/medicines?low_stock=true&limit=1"), []);
  const names = Object.fromEntries((meds.data?.items ?? []).map((m) => [m.id, m.name]));

  async function sell(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget; const f = new FormData(form);
    setResult(null);
    const r = await act.run(() => post("/sales", { medicine_id: Number(f.get("medicine")), quantity: Number(f.get("qty")), movement_type: String(f.get("kind")) }));
    if (r) { setResult(r); form.reset(); void moves.reload(); void meds.reload(); void low.reload(); }
  }

  return (
    <div>
      <PageHeader title="Inventory" subtitle="Record sales or dispensing (stock is taken first-expired-first-out from non-expired batches) and review the full movement history." />
      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        <Stat label="Medicines tracked" value={num(meds.data?.total)} />
        <Stat label="Below minimum" value={num(low.data?.total)} tone={(low.data?.total ?? 0) > 0 ? "warn" : "good"} hint="Usable (non-expired) stock under the threshold" />
      </div>
      <Section title="Record sale / dispensing">
        <form onSubmit={sell} className="flex flex-wrap items-end gap-3">
          <label className="block space-y-1.5"><span className="text-sm font-medium">Medicine</span><select name="medicine" required className="h-10 w-72 rounded-md border border-border bg-background px-3 text-sm">{meds.data?.items.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.available_stock} usable)</option>)}</select></label>
          <Field label="Quantity"><Input name="qty" type="number" min="1" required className="w-28" /></Field>
          <label className="block space-y-1.5"><span className="text-sm font-medium">Type</span><select name="kind" className="h-10 rounded-md border border-border bg-background px-3 text-sm"><option value="sale">Sale</option><option value="dispense">Dispense</option></select></label>
          <Button type="submit" disabled={act.busy}>{act.busy ? "Recording…" : "Record"}</Button>
        </form>
        <div className="mt-3"><ErrorText error={act.error} /></div>
        {result && (
          <div className="mt-3 rounded-md border border-border bg-muted p-3 text-sm">
            <div className="font-medium">Recorded {result.quantity} units, allocated FEFO:</div>
            <ul className="ml-4 list-disc">{result.allocations.map((a: Row) => <li key={a.batch_id}>{a.quantity} from batch {a.batch_number} (expires {a.expiration_date})</li>)}</ul>
          </div>)}
      </Section>
      <Section title="Movement history (append-only ledger)">
        <div className="mb-3 flex flex-wrap gap-3">
          <Select value={type} onChange={(v) => { setType(v); setOffset(0); }}>{TYPES.map((t) => <option key={t} value={t}>{t ? t.replace("_", " ") : "All types"}</option>)}</Select>
          <Select value={med} onChange={(v) => { setMed(v); setOffset(0); }}><option value="">All medicines</option>{meds.data?.items.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select>
        </div>
        <ErrorText error={moves.error} />
        {moves.loading && !moves.data ? <Loading /> : (
          <Table>
            <thead><tr><Th>When</Th><Th>Medicine</Th><Th>Type</Th><Th right>Quantity</Th><Th>Batch</Th><Th>Reason</Th></tr></thead>
            <tbody>{moves.data?.items.map((m) => (
              <tr key={m.id}><Td>{new Date(m.occurred_at).toLocaleString()}</Td><Td>{names[m.medicine_id] ?? m.medicine_id}</Td><Td className="capitalize">{m.movement_type.replace("_", " ")}</Td>
                <Td right>{m.quantity > 0 ? `+${m.quantity}` : m.quantity}</Td><Td>#{m.batch_id}</Td><Td>{m.reason ?? ""}</Td></tr>))}</tbody>
          </Table>)}
        <Pager total={moves.data?.total ?? 0} limit={LIMIT} offset={offset} onChange={setOffset} />
      </Section>
    </div>
  );
}
