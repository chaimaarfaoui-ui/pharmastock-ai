"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Empty, ErrorText, PageHeader, Section, Table, Td, Th } from "@/components/common";
import { api, downloadFile, runJob, type Row } from "@/lib/api";
import { useAction, useFetch } from "@/lib/hooks";

const LABELS: Record<string, string> = { inventory_status: "Inventory status", demand_forecast: "Demand forecasts", shortage_alerts: "Shortage alerts", expiration_risk: "Expiration risks", supplier_performance: "Supplier performance", purchasing_recommendations: "Purchasing recommendations" };

export default function ReportsPage() {
  const list = useFetch(() => api<Row>("/reports"), []); const act = useAction(); const [working, setWorking] = useState<string | null>(null);
  async function make(type: string, format: string) {
    setWorking(`${type}-${format}`);
    const r = await act.run(() => runJob("/reports", { report_type: type, format }));
    setWorking(null);
    if (r) { void list.reload(); await act.run(() => downloadFile(`/reports/${r.report_id}/download`, r.filename)); }
  }
  return (
    <div>
      <PageHeader title="Reports" subtitle="Generate CSV or PDF reports from current data. Reports are labelled when they contain synthetic demo data and carry the same estimate disclaimers as the app." />
      <ErrorText error={act.error ?? list.error} />
      <Section title="Generate">
        <Table><thead><tr><Th>Report</Th><Th>CSV</Th><Th>PDF</Th></tr></thead>
          <tbody>{(list.data?.types ?? Object.keys(LABELS)).map((t: string) => <tr key={t}><Td>{LABELS[t] ?? t}</Td>
            {["csv", "pdf"].map((f) => <Td key={f}><Button size="sm" variant="outline" disabled={!!working} onClick={() => make(t, f)}>{working === `${t}-${f}` ? "Generating…" : `Download ${f.toUpperCase()}`}</Button></Td>)}</tr>)}</tbody></Table>
      </Section>
      <Section title="Previously generated">
        {!list.data?.items.length ? <Empty>No reports generated yet.</Empty> : <Table><thead><tr><Th>File</Th><Th>Created</Th><Th>Size</Th><Th /></tr></thead>
          <tbody>{list.data.items.map((r: Row) => <tr key={r.id}><Td>{r.filename}</Td><Td>{new Date(r.created_at).toLocaleString()}</Td><Td>{(r.size_bytes / 1024).toFixed(1)} KB</Td>
            <Td right><Button size="sm" variant="outline" onClick={() => act.run(() => downloadFile(`/reports/${r.id}/download`, r.filename))}>Download</Button></Td></tr>)}</tbody></Table>}
      </Section>
    </div>
  );
}
