"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge, ErrorText, Loading, PageHeader, Section } from "@/components/common";
import { api, put, runJob } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useAction, useFetch } from "@/lib/hooks";

export default function SettingsPage() {
  const { user } = useAuth();
  const s = useFetch(() => api<Record<string, any>>("/settings"), []); // eslint-disable-line @typescript-eslint/no-explicit-any
  const act = useAction(); const seed = useAction(); const [saved, setSaved] = useState(false); const [prog, setProg] = useState<number | null>(null);
  const d = s.data;
  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget); setSaved(false);
    const days = String(f.get("days")).split(",").map((x) => Number(x.trim())).filter((x) => x > 0);
    if (await act.run(() => put("/settings", { service_level: Number(f.get("sl")), default_lead_time_days: Number(f.get("lead")), review_period_days: Number(f.get("review")), expiry_warning_days: days,
      holding_cost_rate: Number(f.get("hold")), forecast_horizon_days: Number(f.get("horizon")) }))) { setSaved(true); void s.reload(); }
  }
  async function loadDemo() {
    if (!window.confirm("Load synthetic demonstration data? It is generated, not real, and will be labelled as such throughout the app.")) return;
    setProg(0);
    const r = await seed.run(() => runJob("/demo/seed", {}, setProg)); setProg(null);
    if (r) window.location.reload();
  }
  if (user?.role === "employee") return <p className="text-sm">Settings are available to pharmacists and managers.</p>;
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Settings" subtitle="Thresholds that drive alerts and recommendations. Changes apply the next time analyses are run." />
      <ErrorText error={s.error} />
      {!d ? <Loading /> : (<>
        <Section title="Alert and planning thresholds">
          <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
            <Field label="Cycle service level (0.5–0.999)"><Input name="sl" type="number" step="0.001" min="0.5" max="0.999" defaultValue={d.service_level} /></Field>
            <Field label="Default lead time (days)"><Input name="lead" type="number" min="1" defaultValue={d.default_lead_time_days} /></Field>
            <Field label="Review period (days)"><Input name="review" type="number" min="1" defaultValue={d.review_period_days} /></Field>
            <Field label="Expiry warning windows (days, comma-separated)"><Input name="days" defaultValue={d.expiry_warning_days.join(", ")} /></Field>
            <Field label="Annual holding cost rate (assumption, 0.2 = 20%)"><Input name="hold" type="number" step="0.01" min="0" max="2" defaultValue={d.holding_cost_rate} /></Field>
            <Field label="Forecast horizon (days)"><Input name="horizon" type="number" min="7" max="90" defaultValue={d.forecast_horizon_days} /></Field>
            <div className="sm:col-span-2"><ErrorText error={act.error} /><Button type="submit" disabled={act.busy}>Save settings</Button>{saved && <span role="status" className="ml-3 text-sm text-emerald-600">Saved</span>}</div>
          </form>
        </Section>
        <Section title="Data source">
          <p className="mb-3 text-sm">This pharmacy&apos;s data is marked <Badge value={d.data_source === "synthetic" ? "warning" : "ok"} label={d.data_source} />. {d.data_source === "synthetic" ? "It was generated for demonstration and is labelled in the UI and in every report." : "Real operational data entered by your team."}</p>
          {user?.role === "admin" && d.data_source !== "synthetic" && <>
            <p className="mb-3 text-sm text-muted-foreground">To explore the platform without real data, load a seeded synthetic dataset (about 20 medicines, 18 months of simulated sales, deliveries and expiries). Only possible while the pharmacy has no medicines.</p>
            <ErrorText error={seed.error} /><Button variant="outline" onClick={loadDemo} disabled={seed.busy}>{seed.busy ? `Generating… ${Math.round((prog ?? 0) * 100)}%` : "Load synthetic demo data"}</Button></>}
        </Section>
      </>)}
    </div>
  );
}
