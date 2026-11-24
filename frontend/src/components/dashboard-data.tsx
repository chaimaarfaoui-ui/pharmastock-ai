"use client";
import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/common";
import { api, qs, type Row } from "@/lib/api";
import { useCategories, useFetch, useSuppliers } from "@/lib/hooks";

export interface Filters { date_from: string; date_to: string; category_id: string; supplier_id: string; status: string }
export const COLORS = ["#0f766e", "#d97706", "#2563eb", "#9333ea", "#dc2626", "#64748b", "#0891b2", "#65a30d"];

export function useDashboard() {
  const [f, setF] = useState<Filters>({ date_from: "", date_to: "", category_id: "", supplier_id: "", status: "" });
  const data = useFetch(() => api<Row>(`/analytics/dashboard${qs({ ...f })}`), [f.date_from, f.date_to, f.category_id, f.supplier_id, f.status]);
  return { f, setF, ...data };
}

export function FilterBar({ f, setF }: { f: Filters; setF: (f: Filters) => void }) {
  const cats = useCategories(); const sups = useSuppliers();
  const set = (k: keyof Filters) => (v: string) => setF({ ...f, [k]: v });
  return (
    <div className="mb-5 flex flex-wrap items-end gap-3 rounded-lg border border-border p-3" role="search" aria-label="Dashboard filters">
      <label className="block space-y-1"><span className="text-xs font-medium">From</span><Input type="date" className="h-9" value={f.date_from} onChange={(e) => set("date_from")(e.target.value)} /></label>
      <label className="block space-y-1"><span className="text-xs font-medium">To</span><Input type="date" className="h-9" value={f.date_to} onChange={(e) => set("date_to")(e.target.value)} /></label>
      <Select label="Category" value={f.category_id} onChange={set("category_id")} className="h-9"><option value="">All</option>{cats.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
      <Select label="Supplier" value={f.supplier_id} onChange={set("supplier_id")} className="h-9"><option value="">All</option>{sups.data?.items.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>
      <Select label="Inventory status" value={f.status} onChange={set("status")} className="h-9"><option value="">All</option><option value="low_stock">Low stock</option><option value="out_of_stock">Out of stock</option><option value="expiring">Expiring soon</option><option value="expired">Has expired stock</option></Select>
      <button className="h-9 rounded-md border border-border px-3 text-sm hover:bg-muted" onClick={() => setF({ date_from: "", date_to: "", category_id: "", supplier_id: "", status: "" })}>Reset</button>
    </div>
  );
}
