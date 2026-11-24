"use client";
import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge, Empty, ErrorText, Loading, PageHeader, Section, Select, Table, Td, Th, num } from "@/components/common";
import { api, patch, post, type Row } from "@/lib/api";
import { useAction, useFetch, useMedicines } from "@/lib/hooks";

export default function ShortagePage() {
  const [level, setLevel] = useState("");
  const list = useFetch(() => api<Row>(`/shortage/alerts?status=active${level ? `&risk_level=${level}` : ""}`), [level]);
  const act = useAction(); const [open, setOpen] = useState<number | null>(null);
  async function evaluate() { if (await act.run(() => post("/shortage/evaluate"))) void list.reload(); }
  async function mark(id: number, status: string) { if (await act.run(() => patch(`/shortage/alerts/${id}`, { status }))) void list.reload(); }
  return (
    <div>
      <PageHeader title="Shortage alerts" subtitle="Risk is an estimate: a demand forecast (predicted) combined with inventory arithmetic (deterministic). It never claims a product will certainly run out."
        actions={<Button onClick={evaluate} disabled={act.busy}>{act.busy ? "Evaluating…" : "Re-evaluate shortage risk"}</Button>} />
      <ErrorText error={list.error ?? act.error} />
      <div className="mb-4"><Select value={level} onChange={setLevel}><option value="">All risk levels</option><option value="high">High</option><option value="medium">Medium</option></Select></div>
      <Section title={`${list.data?.items.length ?? 0} active alerts`}>
        {list.loading && !list.data ? <Loading /> : !list.data?.items.length ? <Empty>No shortage risk right now. If data changed, re-evaluate.</Empty> : (
          <Table><thead><tr><Th>Medicine</Th><Th>Risk</Th><Th right>Usable stock</Th><Th right>Days of cover</Th><Th right>Lead time (d)</Th><Th>First reason</Th><Th /></tr></thead>
            <tbody>{list.data.items.flatMap((a: Row) => { const c = a.calculation.deterministic; return [
              <tr key={a.id}><Td className="font-medium">{a.medicine}</Td><Td><Badge value={a.risk_level} /> {a.status === "reviewed" && <Badge value="info" label="reviewed" />}</Td><Td right>{num(c.usable_stock)}</Td><Td right>{c.days_of_cover ?? "—"}</Td><Td right>{c.lead_time_days}</Td>
                <Td className="max-w-md">{a.reasons[0]}</Td>
                <Td><div className="flex gap-1"><Button size="sm" variant="outline" onClick={() => setOpen(open === a.id ? null : a.id)}>{open === a.id ? "Hide" : "Calculation"}</Button>
                  {a.status === "open" && <Button size="sm" variant="outline" onClick={() => mark(a.id, "reviewed")}>Mark reviewed</Button>}<Button size="sm" variant="outline" onClick={() => mark(a.id, "resolved")}>Resolve</Button></div></Td></tr>,
              open === a.id && <tr key={`${a.id}-c`}><Td className="bg-muted" ><span /></Td><td colSpan={6} className="border-b border-border bg-muted p-3 text-xs"><Calc a={a} /></td></tr>]; })}</tbody></Table>)}
      </Section>
      <Simulator />
    </div>
  );
}

function Calc({ a }: { a: Row }) {
  const d = a.calculation.deterministic, p = a.calculation.predicted_input;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div><div className="mb-1 font-semibold">Deterministic inventory calculation</div>
        <ul className="space-y-0.5"><li>Usable (non-expired) stock: {d.usable_stock}</li><li>Lead time: {d.lead_time_days} days ({d.lead_time_source})</li>
          <li>Open orders: {d.open_orders.length ? d.open_orders.map((o: Row) => `${o.quantity} units arriving ${o.arrival}${o.overdue ? " (overdue)" : ""}`).join("; ") : "none"}</li>
          <li>Safety stock = z × σ × √L = {d.safety_stock} (z={d.z}, service level {d.service_level})</li><li>Reorder point: {d.reorder_point}</li>
          <li>Projected lowest stock in window: {d.projected_min_stock}</li>{d.first_projected_stockout && <li>First projected stockout: {d.first_projected_stockout}</li>}</ul></div>
      <div><div className="mb-1 font-semibold">Predicted input</div>
        <ul className="space-y-0.5"><li>Demand source: {p.demand_source}</li><li>Mean daily demand: {p.mean_daily_demand}</li><li>Variability σ/day: {p.sigma_daily}</li><li>Expected demand over {d.window_days} days: {p.expected_demand_over_window}</li></ul>
        <ul className="mt-2 list-disc pl-4">{a.reasons.map((r: string) => <li key={r}>{r}</li>)}</ul>
        <p className="mt-2 text-muted-foreground">{a.calculation.disclaimer}</p></div>
    </div>
  );
}

function Simulator() {
  const meds = useMedicines(); const act = useAction(); const [res, setRes] = useState<Row | null>(null);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget);
    const r = await act.run(() => post("/shortage/simulate", { medicine_id: Number(f.get("medicine")), demand_multiplier: Number(f.get("dm") || 1), lead_time_days: f.get("lead") ? Number(f.get("lead")) : null,
      order_quantity: Number(f.get("qty") || 0), order_arrives_in_days: Number(f.get("arrive") || 7) }));
    if (r) setRes(r);
  }
  const data = res ? res.baseline.projection.map((v: number, i: number) => ({ day: i + 1, baseline: v, scenario: res.scenario.projection[i] })) : [];
  return (
    <Section title="What-if simulator">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <label className="block space-y-1.5"><span className="text-sm font-medium">Medicine</span><select name="medicine" required className="h-10 w-64 rounded-md border border-border bg-background px-3 text-sm">{meds.data?.items.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
        <Field label="Demand × (1 = forecast)"><Input name="dm" type="number" step="0.1" min="0.1" max="5" defaultValue="1.5" className="w-32" /></Field>
        <Field label="Lead time (days)"><Input name="lead" type="number" min="1" placeholder="current" className="w-28" /></Field>
        <Field label="Extra order qty"><Input name="qty" type="number" min="0" defaultValue="0" className="w-28" /></Field>
        <Field label="…arrives in (days)"><Input name="arrive" type="number" min="1" defaultValue="5" className="w-28" /></Field>
        <Button type="submit" disabled={act.busy}>Simulate</Button>
      </form>
      <div className="mt-3"><ErrorText error={act.error} /></div>
      {res && <div className="mt-4">
        <div className="mb-2 flex gap-4 text-sm"><span>Baseline: <Badge value={res.baseline.risk_level} /></span><span>Scenario: <Badge value={res.scenario.risk_level} /></span></div>
        <div className="h-64" role="img" aria-label="Projected stock, baseline versus scenario"><ResponsiveContainer><LineChart data={data}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="day" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Legend /><ReferenceLine y={0} stroke="#dc2626" />
          <Line dataKey="baseline" stroke="#334155" dot={false} name="Baseline" /><Line dataKey="scenario" stroke="#d97706" dot={false} name="Scenario" /></LineChart></ResponsiveContainer></div>
        <ul className="mt-2 list-disc pl-5 text-sm">{res.scenario.reasons.map((r: string) => <li key={r}>{r}</li>)}</ul><p className="mt-2 text-xs text-muted-foreground">{res.note}</p></div>}
    </Section>
  );
}
