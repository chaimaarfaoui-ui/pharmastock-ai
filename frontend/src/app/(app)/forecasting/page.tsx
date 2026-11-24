"use client";
import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import { Badge, ErrorText, Loading, PageHeader, Section, Select, Stat, Table, Td, Th, num } from "@/components/common";
import { api, runJob, type Row } from "@/lib/api";
import { useAction, useFetch, useMedicines } from "@/lib/hooks";

export default function ForecastingPage() {
  const meds = useMedicines(); const act = useAction();
  const [med, setMed] = useState(""); const [horizon, setHorizon] = useState("30"); const [progress, setProgress] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const id = med || (meds.data?.items[0]?.id ? String(meds.data.items[0].id) : "");
  const fc = useFetch(() => (id ? api<Row>(`/forecasts/${id}?horizon=${horizon}`) : Promise.resolve(null)), [id, horizon]);
  const evals = useFetch(() => api<Row>("/forecasts/evaluations"), []);

  async function run() {
    setMsg(null); setProgress(0);
    const r = await act.run(() => runJob("/forecasts/run", { refresh_alerts: true }, setProgress));
    setProgress(null);
    if (r) { setMsg(`Forecasts generated for ${r.medicines} medicines; shortage, expiry and reorder analyses were refreshed.`); void fc.reload(); void evals.reload(); }
  }

  const d = fc.data;
  const hist = (d?.history ?? []).map((h: Row) => ({ date: h.date, actual: h.censored ? null : h.units, censored: h.censored ? h.units : null }));
  const future = (d?.forecast ?? []).map((f: Row) => ({ date: f.date, forecast: f.yhat, band: [f.lower, f.upper] }));
  const bt = d?.backtest ? d.backtest.dates.map((dt: string, i: number) => ({ date: dt, bt_actual: d.backtest.actual[i], bt_pred: d.backtest.predicted[i] })) : [];

  return (
    <div>
      <PageHeader title="Demand forecasting" subtitle="Forecasts are estimates compared by rolling-origin validation (no random splits). Days when a product was out of stock are treated as censored, never as zero demand."
        actions={<Button onClick={run} disabled={act.busy}>{act.busy ? `Running… ${Math.round((progress ?? 0) * 100)}%` : "Run forecasts"}</Button>} />
      <ErrorText error={act.error ?? fc.error} />
      {msg && <p role="status" className="mb-3 rounded-md border border-border bg-muted px-3 py-2 text-sm">{msg}</p>}
      <div className="mb-4 flex flex-wrap gap-3">
        <Select value={id} onChange={setMed}>{meds.data?.items.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select>
        <Select value={horizon} onChange={setHorizon}><option value="7">7 days</option><option value="30">30 days</option><option value="60">60 days</option></Select>
      </div>
      {fc.loading && !d ? <Loading /> : d && (<>
        {!d.model && <p className="mb-4 text-sm text-muted-foreground">No forecast yet for this medicine. Press “Run forecasts”.</p>}
        {d.model && <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Stat label="Next 7 days" value={num(d.totals.next_7_days)} hint="units (expected)" />
          <Stat label="Next 30 days" value={num(d.totals.next_30_days)} hint="units (expected)" />
          <Stat label="Next 60 days" value={num(d.totals.next_60_days)} hint="units (expected)" />
          <Stat label="Model" value={<span className="text-lg">{d.model}</span>} hint={d.confidence === "validated" ? "validated by backtest" : "low confidence: not validated"} tone={d.confidence === "validated" ? undefined : "warn"} />
          <Stat label="Validation WAPE" value={d.metrics?.wape != null ? `${(d.metrics.wape * 100).toFixed(0)}%` : "n/a"} hint={d.metrics ? `MAE ${d.metrics.mae?.toFixed(2)} · RMSE ${d.metrics.rmse?.toFixed(2)} · ${d.metrics.n_folds} folds` : undefined} />
        </div>}
        <Section title="History and forecast (units per day)">
          <div className="h-80 w-full" role="img" aria-label="Demand history and forecast chart">
            <ResponsiveContainer><ComposedChart data={[...hist, ...future]}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Legend />
              <Area dataKey="band" name="Likely range (nominal 80%, ~75% in testing)" stroke="none" fill="#0f766e" fillOpacity={0.15} />
              <Line dataKey="actual" name="Actual (observed)" stroke="#334155" dot={false} strokeWidth={1.5} connectNulls={false} />
              <Line dataKey="censored" name="Out-of-stock day (censored: true demand unknown)" stroke="#dc2626" dot={{ r: 2 }} strokeWidth={0} />
              <Line dataKey="forecast" name="Forecast" stroke="#0f766e" dot={false} strokeWidth={2} />
            </ComposedChart></ResponsiveContainer>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">{d.uncertainty_note} {d.n_censored_days} out-of-stock days in this product&apos;s history are excluded from scoring and imputed for training.</p>
        </Section>
        {bt.length > 0 && <Section title="Actual vs predicted (latest validation window, out-of-sample)">
          <div className="h-64 w-full" role="img" aria-label="Actual versus predicted validation chart"><ResponsiveContainer><ComposedChart data={bt}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={30} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Legend />
            <Line dataKey="bt_actual" name="Actual" stroke="#334155" dot={false} connectNulls={false} /><Line dataKey="bt_pred" name="Predicted" stroke="#d97706" dot={false} />
          </ComposedChart></ResponsiveContainer></div></Section>}
        {d.explanation && <Section title="What drives this forecast">
          <div className="grid gap-4 text-sm sm:grid-cols-3">
            <div><div className="font-medium">Recent level</div>{num(d.explanation.level_last_28d, 2)} units/day (last 28 days){d.explanation.change_vs_prior_28d_pct != null && <div className="text-muted-foreground">{d.explanation.change_vs_prior_28d_pct}% vs previous 28 days</div>}</div>
            <div><div className="font-medium">Weekday pattern (1.0 = average)</div>{["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((n, i) => <span key={n} className="mr-2 inline-block">{n} {d.explanation.weekday_profile?.[String(i)] ?? "—"}</span>)}</div>
            {d.explanation.feature_importance && <div><div className="font-medium">Feature importance (tree model)</div>{Object.entries(d.explanation.feature_importance).map(([k, v]) => <div key={k}>{k}: {((v as number) * 100).toFixed(0)}%</div>)}</div>}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">{d.explanation.note}</p>
        </Section>}
        {d.candidates.length > 0 && <Section title="Model comparison (validation, lower is better)">
          <Table><thead><tr><Th>Model</Th><Th right>WAPE</Th><Th right>MAE</Th><Th right>RMSE</Th><Th /></tr></thead>
            <tbody>{[...d.candidates].sort((a: Row, b: Row) => (a.wape ?? 9) - (b.wape ?? 9)).map((c: Row) => <tr key={c.model}><Td>{c.model}</Td><Td right>{c.wape != null ? `${(c.wape * 100).toFixed(1)}%` : "—"}</Td><Td right>{c.mae?.toFixed(2)}</Td><Td right>{c.rmse?.toFixed(2)}</Td><Td>{c.is_selected && <Badge value="ok" label="selected" />}</Td></tr>)}</tbody></Table>
        </Section>}
        {d.notes?.length > 0 && <ul className="mb-5 list-disc pl-5 text-xs text-muted-foreground">{d.notes.map((n: string) => <li key={n}>{n}</li>)}</ul>}
      </>)}
      <Section title="Selected model vs moving-average baseline, all medicines">
        {evals.loading && !evals.data ? <Loading /> : !evals.data?.items.length ? <p className="text-sm text-muted-foreground">No evaluations yet.</p> : (
          <Table><thead><tr><Th>Medicine</Th><Th>Selected</Th><Th right>Selected WAPE</Th><Th right>Baseline WAPE</Th><Th right>Out-of-stock days</Th><Th>Confidence</Th><Th>Data</Th></tr></thead>
            <tbody>{evals.data.items.map((e: Row) => <tr key={e.medicine_id}><Td>{e.medicine}</Td><Td>{e.selected_model}</Td><Td right>{e.selected_wape != null ? `${(e.selected_wape * 100).toFixed(1)}%` : "—"}</Td><Td right>{e.baseline_wape != null ? `${(e.baseline_wape * 100).toFixed(1)}%` : "—"}</Td><Td right>{e.n_censored_days}</Td><Td>{e.confidence}</Td><Td>{e.data_source}</Td></tr>)}</tbody></Table>)}
      </Section>
    </div>
  );
}
