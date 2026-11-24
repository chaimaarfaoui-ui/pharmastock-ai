"use client";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, ErrorText, Loading, PageHeader, Section, Table, Td, Th, money, num, pct } from "@/components/common";
import { COLORS, FilterBar, useDashboard } from "@/components/dashboard-data";

export default function AnalyticsPage() {
  const { f, setF, data: d, error, loading } = useDashboard();
  const s = d?.series;
  // pivot movements into one row per month with a column per type
  const types = Array.from(new Set((s?.stock_movements ?? []).map((m: { type: string }) => m.type))) as string[];
  const mv: Record<string, Record<string, number | string>> = {};
  (s?.stock_movements ?? []).forEach((m: { month: string; type: string; units: number }) => { mv[m.month] ??= { month: m.month }; mv[m.month][m.type] = m.units; });
  return (
    <div>
      <PageHeader title="Analytics" subtitle="Movements, categories, purchasing and supplier performance, all computed from recorded transactions and filterable." />
      <FilterBar f={f} setF={setF} /><ErrorText error={error} />
      {loading && !d ? <Loading /> : d && (<>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card><CardHeader><CardTitle>Stock movements by month (units)</CardTitle></CardHeader><CardContent>{!Object.keys(mv).length ? <Empty>No movements in range.</Empty> :
            <div className="h-64" role="img" aria-label="Stock movements stacked bars"><ResponsiveContainer><BarChart data={Object.values(mv)}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="month" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Legend />{types.map((t, i) => <Bar key={t} dataKey={t} stackId="a" fill={COLORS[i % COLORS.length]} name={t.replace("_", " ")} />)}</BarChart></ResponsiveContainer></div>}</CardContent></Card>
          <Card><CardHeader><CardTitle>Stock value by category</CardTitle></CardHeader><CardContent>{!s.category_value.length ? <Empty>No stock.</Empty> :
            <div className="h-64" role="img" aria-label="Category value pie chart"><ResponsiveContainer><PieChart><Pie data={s.category_value} dataKey="value" nameKey="category" outerRadius={90} label={(e) => e.name}>{s.category_value.map((_: unknown, i: number) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer></div>}</CardContent></Card>
          <Card><CardHeader><CardTitle>Purchasing: goods received (value)</CardTitle></CardHeader><CardContent>{!s.purchasing_spend.length ? <Empty>No deliveries in range.</Empty> :
            <div className="h-64" role="img" aria-label="Purchasing spend"><ResponsiveContainer><BarChart data={s.purchasing_spend}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="month" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Bar dataKey="spend" fill="#2563eb" name="Spend" /></BarChart></ResponsiveContainer></div>}</CardContent></Card>
          <Card><CardHeader><CardTitle>Purchasing: orders placed (value and count)</CardTitle></CardHeader><CardContent>{!s.purchasing_trend.length ? <Empty>No orders in range.</Empty> :
            <div className="h-64" role="img" aria-label="Purchasing trend"><ResponsiveContainer><BarChart data={s.purchasing_trend}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="month" tick={{ fontSize: 11 }} /><YAxis yAxisId="l" tick={{ fontSize: 11 }} /><YAxis yAxisId="r" orientation="right" tick={{ fontSize: 11 }} /><Tooltip /><Legend /><Bar yAxisId="l" dataKey="order_value" fill="#0f766e" name="Order value" /><Bar yAxisId="r" dataKey="orders" fill="#d97706" name="Orders" /></BarChart></ResponsiveContainer></div>}</CardContent></Card>
        </div>
        <div className="mt-5" />
        <Section title="Supplier performance (selected period)">
          {!s.supplier_performance.length ? <Empty>No suppliers.</Empty> : (<>
            <div className="mb-4 h-56" role="img" aria-label="Supplier on-time rate"><ResponsiveContainer><BarChart data={s.supplier_performance.filter((p: { on_time_rate: number | null }) => p.on_time_rate !== null).map((p: { supplier: string; on_time_rate: number }) => ({ supplier: p.supplier, on_time: Math.round(p.on_time_rate * 100) }))}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="supplier" tick={{ fontSize: 11 }} /><YAxis domain={[0, 100]} tick={{ fontSize: 11 }} /><Tooltip /><Bar dataKey="on_time" fill="#0f766e" name="On-time %" /></BarChart></ResponsiveContainer></div>
            <Table><thead><tr><Th>Supplier</Th><Th right>Deliveries</Th><Th right>Avg lead (d)</Th><Th right>Quoted (d)</Th><Th right>On-time</Th><Th right>Delayed</Th><Th right>Spend</Th><Th>Data-based note</Th></tr></thead>
              <tbody>{s.supplier_performance.map((p: Record<string, number | string | null>) => <tr key={String(p.supplier_id)}><Td>{p.supplier}</Td><Td right>{num(p.deliveries as number)}</Td><Td right>{num(p.avg_lead_time_days as number, 1)}</Td><Td right>{num(p.quoted_lead_time_days as number)}</Td><Td right>{pct(p.on_time_rate as number)}</Td><Td right>{num(p.delayed_orders as number)}</Td><Td right>{money(p.total_spend as number)}</Td><Td className="max-w-sm text-xs">{p.recommendation}</Td></tr>)}</tbody></Table></>)}
        </Section>
      </>)}
    </div>
  );
}
