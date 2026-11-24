"use client";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge, Empty, ErrorText, PageHeader, Section, Select, Table, Td, Th } from "@/components/common";
import { type Row, upload } from "@/lib/api";
import { useAction } from "@/lib/hooks";

const KINDS: Record<string, { label: string; help: string; template: string }> = {
  medicines: { label: "1. Medicines", help: "Your catalogue. Names must be unique per dosage and formulation.",
    template: "name,brand,active_ingredient,dosage,formulation,category,purchase_price,selling_price,min_stock_threshold\nParacetamol 500mg,Generic,paracetamol,500mg,tablet,Analgesics,0.05,0.08,100\n" },
  receipts: { label: "2. Stock receipts (opening stock and deliveries)", help: "One row per batch. Use received_date for past deliveries. The medicine name must match exactly.",
    template: "medicine,batch_number,expiration_date,quantity,unit_cost,received_date,supplier\nParacetamol 500mg,B2026-01,2027-06-30,500,0.05,2026-01-15,\n" },
  sales: { label: "3. Sales history", help: "One row per day and medicine (or per sale). Needs stock received on or before that date; rows are applied oldest first, first-expired-first-out.",
    template: "date,medicine,quantity,unit_price,type\n2026-02-01,Paracetamol 500mg,12,0.08,sale\n" },
};

export default function ImportPage() {
  const [kind, setKind] = useState("medicines"); const [file, setFile] = useState<File | null>(null);
  const [check, setCheck] = useState<Row | null>(null); const [done, setDone] = useState<Row | null>(null);
  const act = useAction(); const input = useRef<HTMLInputElement>(null);

  const reset = () => { setCheck(null); setDone(null); };
  async function send(dry: boolean) {
    if (!file) return;
    const form = new FormData(); form.append("file", file);
    const r = await act.run(() => upload(`/imports/${kind}?dry_run=${dry}`, form));
    if (!r) return;
    if (dry) { setCheck(r); setDone(null); } else { setDone(r); setCheck(null); setFile(null); if (input.current) input.current.value = ""; }
  }
  function template() {
    const url = URL.createObjectURL(new Blob([KINDS[kind].template], { type: "text/csv" }));
    const a = document.createElement("a"); a.href = url; a.download = `${kind}-template.csv`; a.click(); URL.revokeObjectURL(url);
  }
  const clean = check && check.error_count === 0;
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Import data" subtitle="Bring your own data in from CSV files. Every file is checked first; nothing is imported unless every row is valid." />
      <p className="mb-4 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
        Import only product, date and quantity data. <b>Never include anything that identifies a patient.</b> Real data must be authorised and anonymised by your organisation first.
      </p>
      <Section title="1. Choose the type and download a template">
        <div className="flex flex-wrap items-end gap-3">
          <Select value={kind} onChange={(v) => { setKind(v); reset(); }} className="w-96">{Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</Select>
          <Button variant="outline" onClick={template}>Download template</Button>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">{KINDS[kind].help} UTF-8 CSV (comma or semicolon), dates as YYYY-MM-DD, up to 5,000 rows and 2 MB. Import in the order 1, 2, 3.</p>
      </Section>
      <Section title="2. Check your file (nothing is saved yet)">
        <div className="flex flex-wrap items-center gap-3">
          <input ref={input} type="file" accept=".csv,text/csv" aria-label="CSV file" onChange={(e) => { setFile(e.target.files?.[0] ?? null); reset(); }} className="text-sm" />
          <Button onClick={() => send(true)} disabled={!file || act.busy}>{act.busy ? "Working…" : "Check file"}</Button>
        </div>
        <div className="mt-3"><ErrorText error={act.error} /></div>
        {check && (
          <div className="mt-3 text-sm">
            <p className="mb-2">{check.rows} rows read. {clean ? <Badge value="ok" label="no problems found" /> : <Badge value="high" label={`${check.error_count} problem(s)`} />}</p>
            {clean && <p className="mb-2">If you import now it will create: {Object.entries(check.would_create).map(([k, v]) => `${v} ${k}`).join(", ")}.</p>}
            {check.warnings.map((w: string) => <p key={w} className="mb-1 text-amber-700 dark:text-amber-300">{w}</p>)}
            {check.errors.length > 0 && <Table><thead><tr><Th>Row</Th><Th>Column</Th><Th>Problem</Th></tr></thead>
              <tbody>{check.errors.map((e: Row, i: number) => <tr key={i}><Td>{e.row}</Td><Td>{e.column ?? "—"}</Td><Td>{e.message}</Td></tr>)}</tbody></Table>}
            {check.errors_truncated && <p className="mt-2 text-muted-foreground">Only the first 100 problems are shown. Fix these and check again.</p>}
          </div>)}
      </Section>
      <Section title="3. Import">
        {done ? <p className="text-sm"><Badge value="ok" label="imported" /> Created: {Object.entries(done.created).map(([k, v]) => `${v} ${k}`).join(", ")}. The change is recorded in the audit log.</p>
          : !clean ? <Empty>Check a file with no problems first.</Empty>
          : <Button onClick={() => send(false)} disabled={act.busy}>Import {check!.rows} rows now</Button>}
      </Section>
    </div>
  );
}
