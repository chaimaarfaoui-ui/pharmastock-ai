"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge, ErrorText, Loading, Modal, PageHeader, Section, Table, Td, Th, money, num, pct } from "@/components/common";
import { api, patch, post, put, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useAction, useFetch, useMedicines } from "@/lib/hooks";

export default function SuppliersPage() {
  const { user } = useAuth();
  const mgr = user?.role !== "employee";
  const list = useFetch(() => api<Page<Row>>("/suppliers?limit=200"), []);
  const perf = useFetch(() => (mgr ? api<Row>("/suppliers/performance") : Promise.resolve(null)), [mgr]);
  const [editing, setEditing] = useState<Row | "new" | null>(null);
  const [terms, setTerms] = useState<Row | null>(null);
  const perfBy = Object.fromEntries((perf.data?.items ?? []).map((p: Row) => [p.supplier_id, p]));

  return (
    <div>
      <PageHeader title="Suppliers" subtitle="Contacts, quoted lead times and measured delivery performance. Metrics are computed from recorded purchase orders and deliveries."
        actions={mgr && <Button onClick={() => setEditing("new")}>Add supplier</Button>} />
      <ErrorText error={list.error ?? perf.error} />
      <Section title="Supplier performance">
        {list.loading && !list.data ? <Loading /> : (
          <Table>
            <thead><tr><Th>Supplier</Th><Th>Contact</Th><Th right>Quoted lead (d)</Th>{mgr && <><Th right>Measured lead (d)</Th><Th right>On-time</Th><Th right>Delayed orders</Th><Th right>Fill rate</Th><Th right>Spend</Th><Th right>Price variation</Th></>}<Th /></tr></thead>
            <tbody>{list.data?.items.map((s) => { const p = perfBy[s.id]; return (
              <tr key={s.id}>
                <Td><div className="font-medium">{s.name}</div>{!s.is_active && <Badge value="low" label="inactive" />}{p?.recommendation && <div className="mt-1 max-w-sm text-xs text-muted-foreground">{p.recommendation}</div>}</Td>
                <Td>{[s.contact_name, s.email, s.phone].filter(Boolean).join(" · ") || "—"}</Td><Td right>{num(s.default_lead_time_days)}</Td>
                {mgr && <><Td right>{num(p?.avg_lead_time_days, 1)}</Td><Td right>{pct(p?.on_time_rate)}</Td><Td right>{num(p?.delayed_orders)}</Td><Td right>{pct(p?.fill_rate)}</Td><Td right>{money(p?.total_spend)}</Td><Td right>{p?.avg_price_variation_pct != null ? `${p.avg_price_variation_pct}%` : "—"}</Td></>}
                <Td right>{mgr && <div className="flex justify-end gap-1"><Button size="sm" variant="outline" onClick={() => setTerms(s)}>Product terms</Button><Button size="sm" variant="outline" onClick={() => setEditing(s)}>Edit</Button></div>}</Td>
              </tr>); })}</tbody>
          </Table>)}
      </Section>
      {mgr && (perf.data?.price_comparison?.length ?? 0) > 0 && (
        <Section title="Price comparison (medicines bought from more than one supplier)">
          <Table><thead><tr><Th>Medicine</Th><Th>Average unit price paid, by supplier</Th></tr></thead>
            <tbody>{perf.data!.price_comparison.map((c: Row) => (
              <tr key={c.medicine_id}><Td>{c.medicine}</Td><Td>{c.suppliers.map((s: Row) => `${s.supplier}: ${money(s.avg_unit_price)} (${s.orders} orders)`).join("  ·  ")}</Td></tr>))}</tbody></Table>
        </Section>)}
      {editing && <SupplierForm sup={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void list.reload(); }} />}
      {terms && <TermsForm sup={terms} onClose={() => setTerms(null)} />}
    </div>
  );
}

function SupplierForm({ sup, onClose, onSaved }: { sup: Row | null; onClose: () => void; onSaved: () => void }) {
  const act = useAction();
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget); const s = (k: string) => String(f.get(k) ?? "").trim() || null;
    await act.run(async () => {
      const body = { name: s("name"), contact_name: s("contact"), email: s("email"), phone: s("phone"), default_lead_time_days: f.get("lead") ? Number(f.get("lead")) : null };
      if (sup) await patch(`/suppliers/${sup.id}`, { ...body, is_active: f.get("active") === "on" }); else await post("/suppliers", body);
      onSaved();
    });
  }
  return (
    <Modal title={sup ? "Edit supplier" : "Add supplier"} onClose={onClose}>
      <form onSubmit={submit} className="grid gap-3">
        <Field label="Name"><Input name="name" required defaultValue={sup?.name} /></Field>
        <Field label="Contact person"><Input name="contact" defaultValue={sup?.contact_name ?? ""} /></Field>
        <Field label="Email"><Input name="email" type="email" defaultValue={sup?.email ?? ""} /></Field>
        <Field label="Phone"><Input name="phone" defaultValue={sup?.phone ?? ""} /></Field>
        <Field label="Quoted lead time (days)"><Input name="lead" type="number" min="0" defaultValue={sup?.default_lead_time_days ?? ""} /></Field>
        {sup && <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="active" defaultChecked={sup.is_active} />Active</label>}
        <ErrorText error={act.error} /><Button type="submit" disabled={act.busy}>Save</Button>
      </form>
    </Modal>
  );
}

function TermsForm({ sup, onClose }: { sup: Row; onClose: () => void }) {
  const meds = useMedicines(); const act = useAction();
  const terms = useFetch(() => api<Row>(`/supplier-products?supplier_id=${sup.id}`), [sup.id]);
  const names = Object.fromEntries((meds.data?.items ?? []).map((m) => [m.id, m.name]));
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget);
    await act.run(async () => {
      await put("/supplier-products", { supplier_id: sup.id, medicine_id: Number(f.get("medicine")), unit_price: Number(f.get("price")), min_order_quantity: Number(f.get("moq") || 1), lead_time_days: f.get("lead") ? Number(f.get("lead")) : null });
      void terms.reload();
    });
  }
  return (
    <Modal title={`Product terms: ${sup.name}`} onClose={onClose} wide>
      <p className="mb-3 text-sm text-muted-foreground">Price, minimum order quantity and lead time per medicine. Reorder recommendations use these terms.</p>
      <Table><thead><tr><Th>Medicine</Th><Th right>Unit price</Th><Th right>Min order qty</Th><Th right>Lead time (d)</Th></tr></thead>
        <tbody>{terms.data?.items.map((t: Row) => <tr key={t.id}><Td>{names[t.medicine_id]}</Td><Td right>{money(t.unit_price)}</Td><Td right>{t.min_order_quantity}</Td><Td right>{t.lead_time_days ?? "—"}</Td></tr>)}</tbody></Table>
      <form onSubmit={submit} className="mt-4 flex flex-wrap items-end gap-3 border-t border-border pt-4">
        <label className="block space-y-1.5"><span className="text-sm font-medium">Medicine</span><select name="medicine" required className="h-10 w-64 rounded-md border border-border bg-background px-3 text-sm">{meds.data?.items.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
        <Field label="Unit price"><Input name="price" type="number" step="0.01" min="0" required className="w-28" /></Field>
        <Field label="Min order qty"><Input name="moq" type="number" min="1" defaultValue="1" className="w-28" /></Field>
        <Field label="Lead time (d)"><Input name="lead" type="number" min="1" className="w-24" /></Field>
        <Button type="submit" disabled={act.busy}>Add / update</Button>
      </form>
      <div className="mt-2"><ErrorText error={act.error} /></div>
    </Modal>
  );
}
