"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge, ErrorText, Loading, Modal, PageHeader, Pager, Section, Select, Table, Td, Th, money, num } from "@/components/common";
import { api, patch, post, qs, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useAction, useCategories, useFetch, useSuppliers } from "@/lib/hooks";

const LIMIT = 25;

export default function MedicinesPage() {
  const { user } = useAuth();
  const canEdit = user?.role !== "employee";
  const [q, setQ] = useState(""); const [cat, setCat] = useState(""); const [low, setLow] = useState(false); const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<Row | "new" | null>(null);
  const list = useFetch(() => api<Page<Row>>(`/medicines${qs({ q, category_id: cat, low_stock: low, limit: LIMIT, offset })}`), [q, cat, low, offset]);
  const cats = useCategories();

  return (
    <div>
      <PageHeader title="Medicines" subtitle="Catalogue of products. Stock is tracked per batch; available stock excludes expired batches."
        actions={canEdit && <Button onClick={() => setEditing("new")}>Add medicine</Button>} />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Input className="w-64" placeholder="Search name, brand, ingredient" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} aria-label="Search" />
        <Select value={cat} onChange={(v) => { setCat(v); setOffset(0); }}><option value="">All categories</option>{cats.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={low} onChange={(e) => { setLow(e.target.checked); setOffset(0); }} />Below minimum only</label>
      </div>
      <ErrorText error={list.error} />
      <Section title={`${list.data?.total ?? 0} medicines`}>
        {list.loading && !list.data ? <Loading /> : (
          <Table>
            <thead><tr><Th>Name</Th><Th>Category</Th><Th>Form</Th><Th right>Available</Th><Th right>Total (incl. expired)</Th><Th right>Minimum</Th><Th right>Cost</Th><Th /></tr></thead>
            <tbody>{list.data?.items.map((m) => (
              <tr key={m.id}>
                <Td><div className="font-medium">{m.name}</div><div className="text-xs text-muted-foreground">{[m.brand, m.active_ingredient].filter(Boolean).join(" · ")}</div></Td>
                <Td>{m.category_name ?? "—"}</Td><Td>{[m.dosage, m.formulation].filter(Boolean).join(" ") || "—"}</Td>
                <Td right>{num(m.available_stock)} {m.below_threshold && <Badge value="high" label="low" className="ml-1" />}</Td>
                <Td right>{num(m.total_stock)}</Td><Td right>{num(m.min_stock_threshold)}</Td><Td right>{money(Number(m.purchase_price))}</Td>
                <Td right>{canEdit && <Button size="sm" variant="outline" onClick={() => setEditing(m)}>Edit</Button>}</Td>
              </tr>))}</tbody>
          </Table>)}
        <Pager total={list.data?.total ?? 0} limit={LIMIT} offset={offset} onChange={setOffset} />
      </Section>
      {editing && <MedicineForm med={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void list.reload(); void cats.reload(); }} />}
    </div>
  );
}

function MedicineForm({ med, onClose, onSaved }: { med: Row | null; onClose: () => void; onSaved: () => void }) {
  const cats = useCategories(); const sups = useSuppliers(); const act = useAction();
  const [newCat, setNewCat] = useState("");
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const s = (k: string) => String(f.get(k) ?? "").trim();
    await act.run(async () => {
      let category_id = s("category_id") ? Number(s("category_id")) : null;
      if (newCat.trim()) category_id = (await post("/categories", { name: newCat.trim() })).id;
      const body = { name: s("name"), brand: s("brand") || null, active_ingredient: s("active_ingredient") || null, dosage: s("dosage") || null,
        formulation: s("formulation") || null, category_id, preferred_supplier_id: s("supplier") ? Number(s("supplier")) : null,
        purchase_price: Number(s("purchase_price") || 0), selling_price: s("selling_price") ? Number(s("selling_price")) : null, min_stock_threshold: Number(s("min") || 0) };
      if (med) await patch(`/medicines/${med.id}`, body); else await post("/medicines", body);
      onSaved();
    });
  }
  return (
    <Modal title={med ? "Edit medicine" : "Add medicine"} onClose={onClose} wide>
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <Field label="Product name"><Input name="name" required defaultValue={med?.name} /></Field>
        <Field label="Brand"><Input name="brand" defaultValue={med?.brand ?? ""} /></Field>
        <Field label="Active ingredient"><Input name="active_ingredient" defaultValue={med?.active_ingredient ?? ""} /></Field>
        <Field label="Dosage"><Input name="dosage" defaultValue={med?.dosage ?? ""} /></Field>
        <Field label="Formulation"><Input name="formulation" defaultValue={med?.formulation ?? ""} /></Field>
        <label className="block space-y-1.5"><span className="text-sm font-medium">Category</span>
          <select name="category_id" defaultValue={med?.category_id ?? ""} className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"><option value="">None</option>{cats.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
        <Field label="…or create a new category"><Input value={newCat} onChange={(e) => setNewCat(e.target.value)} /></Field>
        <label className="block space-y-1.5"><span className="text-sm font-medium">Preferred supplier</span>
          <select name="supplier" defaultValue={med?.preferred_supplier_id ?? ""} className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"><option value="">None</option>{sups.data?.items.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <Field label="Purchase price"><Input name="purchase_price" type="number" step="0.01" min="0" defaultValue={med?.purchase_price ?? 0} /></Field>
        <Field label="Selling price (optional)"><Input name="selling_price" type="number" step="0.01" min="0" defaultValue={med?.selling_price ?? ""} /></Field>
        <Field label="Minimum stock threshold"><Input name="min" type="number" min="0" defaultValue={med?.min_stock_threshold ?? 0} /></Field>
        <div className="sm:col-span-2"><ErrorText error={act.error} /><Button type="submit" disabled={act.busy}>{act.busy ? "Saving…" : "Save"}</Button></div>
      </form>
    </Modal>
  );
}
