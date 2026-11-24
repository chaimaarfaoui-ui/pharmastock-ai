"use client";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { ErrorText, PageHeader, Section, Table, Td, Th, money, pct } from "@/components/common";
import { post, type Row } from "@/lib/api";
import { useAction, useMedicines } from "@/lib/hooks";

export default function SimulationPage() {
  const meds = useMedicines(); const act = useAction(); const [res, setRes] = useState<Row | null>(null);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget); const n = (k: string) => (f.get(k) ? Number(f.get(k)) : undefined);
    const r = await act.run(() => post("/simulations/policies", { medicine_id: f.get("medicine") ? Number(f.get("medicine")) : undefined, mean_daily: n("mean"), sigma_daily: n("sigma"), demand_multiplier: n("dm") ?? 1,
      lead_time_days: n("lead"), lead_time_multiplier: n("lm") ?? 1, service_level: n("sl") ?? 0.95, budget_per_30_days: n("budget"), shelf_life_days: n("shelf") ?? 365, runs: 60 }));
    if (r) setRes(r);
  }
  const rows = res ? Object.entries(res.policies as Record<string, Row>) : [];
  return (
    <div>
      <PageHeader title="Scenario simulation" subtitle="Compare replenishment policies in a Monte Carlo simulation under assumptions you control. It is a what-if tool, not a forecast, and it never changes real purchasing." />
      <Section title="Assumptions">
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block space-y-1.5 lg:col-span-2"><span className="text-sm font-medium">Base on medicine (optional)</span><select name="medicine" className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"><option value="">Manual inputs below</option>{meds.data?.items.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
          <Field label="Mean demand/day (manual)"><Input name="mean" type="number" step="0.1" min="0" /></Field>
          <Field label="Demand σ/day (manual)"><Input name="sigma" type="number" step="0.1" min="0" /></Field>
          <Field label="Demand ×"><Input name="dm" type="number" step="0.1" min="0.1" max="5" defaultValue="1" /></Field>
          <Field label="Lead time (days)"><Input name="lead" type="number" min="1" placeholder="from supplier" /></Field>
          <Field label="Lead time ×"><Input name="lm" type="number" step="0.25" min="0.25" max="4" defaultValue="1" /></Field>
          <Field label="Service level"><Input name="sl" type="number" step="0.01" min="0.5" max="0.999" defaultValue="0.95" /></Field>
          <Field label="Budget per 30 days (optional)"><Input name="budget" type="number" min="0" /></Field>
          <Field label="Shelf life (days)"><Input name="shelf" type="number" min="7" defaultValue="365" /></Field>
          <div className="flex items-end"><Button type="submit" disabled={act.busy}>{act.busy ? "Simulating…" : "Run simulation"}</Button></div>
        </form>
        <div className="mt-3"><ErrorText error={act.error} /></div>
      </Section>
      {res && <Section title="Policy comparison">
        <p className="mb-3 text-sm text-muted-foreground">Inputs: {res.inputs.mean_daily.toFixed(1)} ± {res.inputs.sigma_daily.toFixed(1)} units/day, lead time {res.inputs.lead_time_days} d, source: {res.inputs.demand_source}. {res.runs} runs, seed {res.seed}.</p>
        <Table><thead><tr><Th>Policy</Th><Th right>Fill rate</Th><Th right>Stockout days</Th><Th right>Avg stock (units)</Th><Th right>Holding</Th><Th right>Expiry waste</Th><Th right>Stockout penalty</Th><Th right>Total cost</Th><Th right>Purchase spend</Th></tr></thead>
          <tbody>{rows.map(([name, v]) => <tr key={name}><Td>{name.replace(/_/g, " ")}</Td><Td right>{pct(v.fill_rate)}</Td><Td right>{pct(v.stockout_day_rate)}</Td><Td right>{v.avg_on_hand_units.toFixed(0)}</Td><Td right>{money(v.holding_cost)}</Td><Td right>{money(v.waste_cost)}</Td><Td right>{money(v.stockout_penalty)}</Td><Td right><b>{money(v.total_cost)}</b></Td><Td right>{money(v.purchase_spend)}</Td></tr>)}</tbody></Table>
        <div className="mt-4 h-56" role="img" aria-label="Policy cost components"><ResponsiveContainer><BarChart data={rows.map(([n, v]) => ({ policy: n.replace(/_/g, " "), holding: v.holding_cost, waste: v.waste_cost, stockout: v.stockout_penalty }))}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="policy" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Legend /><Bar dataKey="holding" stackId="a" fill="#2563eb" /><Bar dataKey="waste" stackId="a" fill="#d97706" /><Bar dataKey="stockout" stackId="a" fill="#dc2626" /></BarChart></ResponsiveContainer></div>
        <p className="mt-2 text-xs text-muted-foreground">{res.note}</p>
      </Section>}
    </div>
  );
}
