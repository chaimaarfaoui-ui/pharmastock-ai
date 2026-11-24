"use client";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, Td, Th, PageHeader } from "@/components/common";
import { post, type Row } from "@/lib/api";

interface Msg { role: "user" | "assistant"; text: string; data?: Row }
const EXAMPLES = ["Which medicines are likely to run out soon?", "Which batches expire within 60 days?", "Which products have declining demand?", "Which suppliers have the longest delivery delays?", "What products should I reorder this week?", "Which medicines have the highest inventory value?"];

export default function AssistantPage() {
  const [msgs, setMsgs] = useState<Msg[]>([]); const [busy, setBusy] = useState(false); const [input, setInput] = useState("");
  const end = useRef<HTMLDivElement>(null);
  async function ask(q: string) {
    if (!q.trim() || busy) return;
    setMsgs((m) => [...m, { role: "user", text: q }]); setInput(""); setBusy(true);
    try { const r = await post("/assistant/ask", { question: q }); setMsgs((m) => [...m, { role: "assistant", text: r.answer, data: r }]); }
    catch (e) { setMsgs((m) => [...m, { role: "assistant", text: e instanceof Error ? e.message : "Request failed" }]); }
    finally { setBusy(false); setTimeout(() => end.current?.scrollIntoView({ behavior: "smooth" }), 50); }
  }
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="AI inventory assistant" subtitle="Ask about your own stock, batches, suppliers, demand and orders. Answers are built only from your database and the platform's calculations. It cannot give medical advice, dosing or treatment guidance." />
      {!msgs.length && <div className="mb-4 flex flex-wrap gap-2">{EXAMPLES.map((e) => <button key={e} onClick={() => ask(e)} className="rounded-full border border-border px-3 py-1.5 text-sm hover:bg-muted">{e}</button>)}</div>}
      <div className="space-y-4" aria-live="polite">
        {msgs.map((m, i) => (
          <div key={i} className={m.role === "user" ? "ml-auto max-w-xl rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground" : "rounded-lg border border-border p-4 text-sm"}>
            <p className={m.data?.refused ? "text-amber-700 dark:text-amber-300" : ""}>{m.text}</p>
            {m.data?.table && m.data.table.rows.length > 0 && <div className="mt-3 overflow-x-auto"><Table><thead><tr>{m.data.table.columns.map((c: string) => <Th key={c}>{c}</Th>)}</tr></thead>
              <tbody>{m.data.table.rows.map((r: unknown[], j: number) => <tr key={j}>{r.map((c, k) => <Td key={k}>{String(c ?? "—")}</Td>)}</tr>)}</tbody></Table></div>}
            {m.data?.how_calculated && <p className="mt-2 text-xs text-muted-foreground">How this was calculated: {m.data.how_calculated}</p>}
          </div>))}
        {busy && <p className="text-sm text-muted-foreground">Looking at your data…</p>}<div ref={end} />
      </div>
      <form onSubmit={(e) => { e.preventDefault(); void ask(input); }} className="sticky bottom-0 mt-4 flex gap-2 bg-background py-3">
        <Input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask an inventory question…" maxLength={500} aria-label="Question" /><Button type="submit" disabled={busy}>Ask</Button>
      </form>
    </div>
  );
}
