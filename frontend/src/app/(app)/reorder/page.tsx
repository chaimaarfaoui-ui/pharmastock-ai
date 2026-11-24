"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge, Empty, ErrorText, Loading, PageHeader, Section, Select, Table, Td, Th, money, num } from "@/components/common";
import { api, post, type Row } from "@/lib/api";
import { useAction, useFetch } from "@/lib/hooks";

export default function ReorderPage() {
  const [status, setStatus] = useState("pending");
  const list = useFetch(() => api<Row>(`/reorder/recommendations?status=${status}`), [status]);
  const act = useAction(); const [msg, setMsg] = useState<string | null>(null);
  const [qty, setQty] = useState<Record<number, string>>({}); const [open, setOpen] = useState<number | null>(null);
  async function generate() { setMsg(null); if (await act.run(() => post("/reorder/generate"))) void list.reload(); }
  async function approve(r: Row) { if (await act.run(() => post(`/reorder/recommendations/${r.id}/approve`, { final_qty: qty[r.id] ? Number(qty[r.id]) : null }))) void list.reload(); }
  async function reject(r: Row) { if (await act.run(() => post(`/reorder/recommendations/${r.id}/reject`))) void list.reload(); }
  async function toPO() { const r = await act.run(() => post("/reorder/create-purchase-orders", {})); if (r) { setMsg(`${r.note} (PO ids: ${r.purchase_order_ids.join(", ")})`); void list.reload(); } }
  return (
    <div>
      <PageHeader title="Reorder recommendations" subtitle="Transparent inventory formulas, not a black box. Every quantity shows its inputs. Recommendations never place orders: approve → draft purchase order → approve and place it yourself."
        actions={<><Button variant="outline" onClick={toPO} disabled={act.busy}>Create draft POs from approved</Button><Button onClick={generate} disabled={act.busy}>Generate recommendations</Button></>} />
      <ErrorText error={list.error ?? act.error} />
      {msg && <p role="status" className="mb-3 rounded-md border border-border bg-muted px-3 py-2 text-sm">{msg}</p>}
      <div className="mb-4"><Select value={status} onChange={setStatus}>{["pending", "approved", "po_created", "rejected", "superseded"].map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}</Select></div>
      {list.loading && !list.data ? <Loading /> : !list.data?.items.length ? <Empty>No {status.replace("_", " ")} recommendations.</Empty> : list.data.items.map((r: Row) => {
        const x = r.explanation, i = x.inputs;
        return (
          <Section key={r.id} title={`${r.medicine}: order ${num(r.recommended_qty)} units`} actions={<Badge value={r.status} />}>
            <div className="grid gap-4 text-sm lg:grid-cols-2">
              <div>
                <p className="mb-2 text-muted-foreground">Trigger: {x.trigger}. Supplier: {r.supplier ?? "none set"}. Estimated cost {money(r.estimated_cost)}.</p>
                <ul className="space-y-0.5">
                  <li>Usable stock {num(i.usable_stock)} + open orders {num(i.open_orders_qty)} − projected expiry waste {num(i.projected_expiry_waste_in_window, 1)} = <b>position {num(i.inventory_position, 1)}</b></li>
                  <li>Lead time {i.lead_time_days} d ({i.lead_time_source}); review {i.review_period_days} d; service level {i.service_level}; MOQ {i.min_order_quantity}</li>
                  <li>Demand {i.mean_daily_demand}/day ± {i.sigma_daily} ({i.demand_source})</li></ul>
                <ul className="mt-2 space-y-0.5 text-xs text-muted-foreground">{Object.values(x.formulas).map((f) => <li key={String(f)}>{String(f)}</li>)}</ul>
                <p className="mt-2">Expected stock when the order arrives (without it): <b>{num(x.expected_position.projected_stock_when_order_arrives_before_this_order, 1)}</b> → after replenishment: <b>{num(x.expected_position.after_replenishment, 1)}</b></p>
                {x.shelf_life_cap.applied && <p className="mt-1 text-amber-700 dark:text-amber-300">Quantity was capped to about 80% of demand over the assumed {x.shelf_life_cap.assumed_shelf_days}-day shelf life.</p>}
              </div>
              <div>
                <Table><thead><tr><Th>Scenario</Th><Th right>Qty</Th><Th right>Cost</Th><Th right>Cover (d)</Th><Th right>P(stockout)*</Th><Th right>Est. waste</Th><Th right>Holding</Th></tr></thead>
                  <tbody>{r.scenarios.map((s: Row) => <tr key={s.label}><Td>{s.label}</Td><Td right>{num(s.quantity)}</Td><Td right>{money(s.purchase_cost)}</Td><Td right>{s.days_of_cover_after ?? "—"}</Td><Td right>{(s.est_stockout_probability_next_cycle * 100).toFixed(1)}%</Td><Td right>{money(s.est_waste_cost)}</Td><Td right>{money(s.est_holding_cost)}</Td></tr>)}</tbody></Table>
                <p className="mt-1 text-xs text-muted-foreground">*Normal-approximation estimate for the next replenishment cycle; waste and holding cost use stated assumptions (holding rate in Settings). Estimates, not guarantees.</p>
              </div>
            </div>
            {r.status === "pending" && <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
              <label className="text-sm">Final quantity <Input type="number" min="1" className="ml-2 inline-block h-9 w-28" placeholder={String(r.recommended_qty)} value={qty[r.id] ?? ""} onChange={(e) => setQty({ ...qty, [r.id]: e.target.value })} /></label>
              <Button size="sm" onClick={() => approve(r)} disabled={act.busy}>Approve{qty[r.id] ? " (modified)" : ""}</Button><Button size="sm" variant="destructive" onClick={() => reject(r)} disabled={act.busy}>Reject</Button>
              <Button size="sm" variant="ghost" onClick={() => setOpen(open === r.id ? null : r.id)}>{open === r.id ? "Hide" : "Show"} disclaimer</Button>
            </div>}
            {open === r.id && <p className="mt-2 text-xs text-muted-foreground">{x.disclaimer}</p>}
          </Section>);
      })}
    </div>
  );
}
