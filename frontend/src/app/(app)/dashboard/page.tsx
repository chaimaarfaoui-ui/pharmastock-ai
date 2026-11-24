"use client";
import Link from "next/link";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorText, Loading, PageHeader, Stat, money, num, pct } from "@/components/common";
import { FilterBar, useDashboard } from "@/components/dashboard-data";
import { useAuth } from "@/lib/auth-context";

const Chart = ({ title, children, empty, label }: { title: string; children: React.ReactElement; empty?: boolean; label: string }) => (
  <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent>
    {empty ? <p className="py-10 text-center text-sm text-muted-foreground">No data for the selected filters.</p> : <div className="h-64" role="img" aria-label={label}><ResponsiveContainer>{children}</ResponsiveContainer></div>}
  </CardContent></Card>
);

export default function DashboardPage() {
  const { user } = useAuth();
  if (!user) return null;
  if (user.role === "employee") return <EmployeeHome name={user.full_name} />;
  return <ManagerDashboard />;
}

function EmployeeHome({ name }: { name: string }) {
  return (
    <div className="mx-auto max-w-2xl space-y-3">
      <h1 className="text-2xl font-semibold">Welcome, {name}</h1>
      <p className="text-sm text-muted-foreground">Your role covers day-to-day stock work. Analytics and purchasing decisions are available to pharmacists and managers.</p>
      <div className="grid gap-3 sm:grid-cols-3">{[["/inventory", "Record sales"], ["/batches", "Receive stock / returns"], ["/purchase-orders", "Record deliveries"]].map(([h, t]) => <Link key={h} href={h} className="rounded-lg border border-border p-4 text-sm font-medium hover:bg-muted">{t}</Link>)}</div>
    </div>
  );
}

function ManagerDashboard() {
  const { f, setF, data: d, error, loading } = useDashboard();
  const k = d?.kpis, s = d?.series;
  const demandByMonth = s?.monthly_demand ?? [];
  return (
    <div>
      <PageHeader title="Dashboard" subtitle="All figures are calculated from your database records and respond to the filters. Stock figures are current; demand and spend use the selected period (default: last 180 days)." />
      <FilterBar f={f} setF={setF} /><ErrorText error={error} />
      {loading && !d ? <Loading /> : d && (<>
        <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Inventory value" value={money(k.total_inventory_value)} hint={`usable ${money(k.usable_inventory_value)} · expired ${money(k.expired_stock_value)}`} />
          <Stat label="Active medicines" value={num(k.active_medicines)} />
          <Stat label="Low-stock products" value={num(k.low_stock_products)} tone={k.low_stock_products ? "warn" : "good"} hint="usable stock under minimum" />
          <Stat label="Forecast shortage risk" value={`${k.shortage_risk_high} high · ${k.shortage_risk_medium} medium`} tone={k.shortage_risk_high ? "bad" : undefined} hint="estimates from open alerts" />
          {Object.entries(k.expiring).map(([days, v]) => <Stat key={days} label={`Batches expiring ≤ ${days} d`} value={num((v as { batches: number }).batches)} hint={`value ${money((v as { value: number }).value)}`} />).slice(0, 2)}
          <Stat label="Estimated waste" value={money(k.estimated_waste_value)} tone={k.estimated_waste_value ? "warn" : "good"} hint="projected unsold + expired, at cost" />
          <Stat label="Purchasing this month" value={money(k.purchasing_cost_current_month)} hint="value of goods received" />
          <Stat label="Inventory turnover" value={k.inventory_turnover.value ?? "—"} hint={k.inventory_turnover.annualised ? `${k.inventory_turnover.annualised}× annualised · COGS ${money(k.inventory_turnover.cogs)}` : "needs sales in period"} />
          <Stat label="Supplier on-time rate" value={pct(k.supplier_on_time_rate)} hint="deliveries vs expected date" />
        </div>
        <p className="mb-3 text-xs text-muted-foreground">Data source: {d.data_source}. {d.filters.note}</p>
        <div className="grid gap-4 lg:grid-cols-2">
          <Chart title="Monthly demand (units sold)" label="Monthly demand bar chart" empty={!demandByMonth.length}><BarChart data={demandByMonth}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="month" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Bar dataKey="units" fill="#0f766e" name="Units" /></BarChart></Chart>
          <Chart title="Actual vs forecast (validation window, out-of-sample)" label="Actual versus forecast demand" empty={!s.actual_vs_forecast.length}><ComposedChart data={s.actual_vs_forecast}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={30} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Legend /><Line dataKey="actual" stroke="#334155" dot={false} name="Actual" /><Line dataKey="forecast" stroke="#d97706" dot={false} name="Forecast" /></ComposedChart></Chart>
          <Chart title="Inventory value over time (month-end, at cost)" label="Inventory value area chart" empty={!s.inventory_value_over_time.length}><AreaChart data={s.inventory_value_over_time}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="month" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Area dataKey="value" stroke="#2563eb" fill="#2563eb" fillOpacity={0.2} name="Value" /></AreaChart></Chart>
          <Chart title="Stock value by time to expiry" label="Expiration risk distribution" empty={!s.expiration_distribution.some((b: { batches: number }) => b.batches)}><BarChart data={s.expiration_distribution}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="bucket" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Bar dataKey="value" fill="#d97706" name="Value" /></BarChart></Chart>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">More charts (movements, categories, purchasing, suppliers) are on the <Link href="/analytics" className="underline">Analytics</Link> page.</p>
      </>)}
    </div>
  );
}
