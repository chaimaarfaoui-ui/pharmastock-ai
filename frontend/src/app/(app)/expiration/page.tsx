"use client";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import { Badge, Empty, ErrorText, Loading, PageHeader, Section, Select, Stat, Table, Td, Th, money, num } from "@/components/common";
import { api, patch, post, type Row } from "@/lib/api";
import { useAction, useFetch } from "@/lib/hooks";

export default function ExpirationPage() {
  const [win, setWin] = useState("");
  const summary = useFetch(() => api<Row>("/expiration/summary"), []);
  const alerts = useFetch(() => api<Row>(`/expiration/alerts?status=active${win ? `&window_days=${win}` : ""}`), [win]);
  const slow = useFetch(() => api<Row>("/expiration/slow-moving"), []);
  const act = useAction(); const [open, setOpen] = useState<number | null>(null);
  const reload = () => { void summary.reload(); void alerts.reload(); void slow.reload(); };
  async function evaluate() { if (await act.run(() => post("/expiration/evaluate"))) reload(); }
  async function mark(id: number, status: string) { if (await act.run(() => patch(`/expiration/alerts/${id}`, { status }))) reload(); }
  const s = summary.data;
  return (
    <div>
      <PageHeader title="Expiration management" subtitle="Projected waste simulates forecast demand served first-expired-first-out against each batch. Expired or unsuitable stock must be written off, never redistributed or sold."
        actions={<Button onClick={evaluate} disabled={act.busy}>{act.busy ? "Evaluating…" : "Re-evaluate expiration risk"}</Button>} />
      <ErrorText error={summary.error ?? alerts.error ?? act.error} />
      {s && <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Estimated waste value" value={money(s.estimated_waste_value)} hint="projected unsold + expired stock at cost" tone={s.estimated_waste_value > 0 ? "warn" : "good"} />
        {s.buckets.slice(0, 3).map((b: Row) => <Stat key={b.bucket} label={`Batches ${b.bucket}`} value={num(b.batches)} hint={`value ${money(b.value)}`} tone={b.bucket === "expired" && b.batches > 0 ? "bad" : undefined} />)}
      </div>}
      {s && <Section title="Stock value by time to expiry"><div className="h-60" role="img" aria-label="Stock value by expiry bucket"><ResponsiveContainer><BarChart data={s.buckets}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="bucket" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Bar dataKey="value" fill="#0f766e" name="Value" /></BarChart></ResponsiveContainer></div></Section>}
      <div className="mb-3"><Select value={win} onChange={setWin}><option value="">All warning windows</option>{(s?.warning_days ?? []).map((d: number) => <option key={d} value={d}>Within {d} days</option>)}<option value="0">Already expired</option></Select></div>
      <Section title={`${alerts.data?.items.length ?? 0} active alerts`}>
        {alerts.loading && !alerts.data ? <Loading /> : !alerts.data?.items.length ? <Empty>No active expiration alerts.</Empty> : (
          <Table><thead><tr><Th>Medicine</Th><Th>Batch</Th><Th>Expires</Th><Th right>Days</Th><Th right>Qty</Th><Th right>Projected leftover</Th><Th right>Value at risk</Th><Th>Type</Th><Th /></tr></thead>
            <tbody>{alerts.data.items.flatMap((a: Row) => [
              <tr key={a.id}><Td className="font-medium">{a.medicine}</Td><Td>{a.batch_number}</Td><Td>{a.expiration_date}</Td><Td right>{a.days_to_expiry}</Td><Td right>{num(a.quantity_remaining)}</Td><Td right>{num(a.projected_leftover, 1)}</Td><Td right>{money(a.at_risk_value)}</Td><Td><Badge value={a.alert_type} /></Td>
                <Td><div className="flex gap-1"><Button size="sm" variant="outline" onClick={() => setOpen(open === a.id ? null : a.id)}>Why</Button><Button size="sm" variant="outline" onClick={() => mark(a.id, "reviewed")}>Reviewed</Button><Button size="sm" variant="outline" onClick={() => mark(a.id, "resolved")}>Resolve</Button></div></Td></tr>,
              open === a.id && <tr key={`${a.id}-c`}><td colSpan={9} className="border-b border-border bg-muted p-3 text-xs"><p>{a.calculation.deterministic.method}</p><p className="mt-1">Demand source: {a.demand_source} · mean {a.calculation.predicted_input.mean_daily_demand} units/day · unit cost {a.calculation.deterministic.unit_cost}</p><p className="mt-1 text-muted-foreground">{a.calculation.disclaimer}</p></td></tr>])}</tbody></Table>)}
      </Section>
      <Section title="Slow-moving stock (more than 180 days of cover)">
        {!slow.data?.items.length ? <Empty>No slow-moving products.</Empty> : <Table><thead><tr><Th>Medicine</Th><Th right>Usable stock</Th><Th right>Avg demand/day</Th><Th right>Days of cover</Th></tr></thead>
          <tbody>{slow.data.items.map((r: Row) => <tr key={r.medicine_id}><Td>{r.medicine}</Td><Td right>{num(r.usable_stock)}</Td><Td right>{r.mean_daily_demand}</Td><Td right>{r.days_of_cover ?? "no recent demand"}</Td></tr>)}</tbody></Table>}
      </Section>
    </div>
  );
}
