"use client";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="text-2xl font-semibold">{title}</h1>{subtitle && <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{subtitle}</p>}</div>
      <div className="flex flex-wrap gap-2">{actions}</div>
    </div>
  );
}

export function ErrorText({ error }: { error?: string | null }) {
  return error ? <p role="alert" className="mb-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p> : null;
}
export const Loading = ({ label = "Loading…" }: { label?: string }) => <p className="py-6 text-sm text-muted-foreground">{label}</p>;
export const Empty = ({ children }: { children: React.ReactNode }) => <p className="py-6 text-center text-sm text-muted-foreground">{children}</p>;

const TONES: Record<string, string> = {
  high: "bg-red-500/15 text-red-700 dark:text-red-300", critical: "bg-red-500/15 text-red-700 dark:text-red-300", expired: "bg-red-500/15 text-red-700 dark:text-red-300",
  medium: "bg-amber-500/20 text-amber-800 dark:text-amber-300", warning: "bg-amber-500/20 text-amber-800 dark:text-amber-300", projected_waste: "bg-amber-500/20 text-amber-800 dark:text-amber-300",
  low: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300", ok: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300", completed: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300", approved: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  info: "bg-sky-500/15 text-sky-700 dark:text-sky-300", ordered: "bg-sky-500/15 text-sky-700 dark:text-sky-300", partially_received: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
};
export function Badge({ value, label, className }: { value: string; label?: string; className?: string }) {
  return <span className={cn("inline-block rounded-full bg-muted px-2 py-0.5 text-xs font-medium capitalize", TONES[value], className)}>{label ?? value.replace(/_/g, " ")}</span>;
}

export function Stat({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: string; tone?: "bad" | "warn" | "good" }) {
  return (
    <Card><CardContent className="p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn("mt-1 text-2xl font-semibold", tone === "bad" && "text-destructive", tone === "warn" && "text-amber-600", tone === "good" && "text-emerald-600")}>{value}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </CardContent></Card>
  );
}

export function Section({ title, children, actions }: { title: string; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <Card className="mb-5">
      <CardHeader className="flex-row items-center justify-between"><CardTitle>{title}</CardTitle>{actions}</CardHeader>
      <CardContent className="overflow-x-auto">{children}</CardContent>
    </Card>
  );
}

export const Table = ({ children }: { children: React.ReactNode }) => <table className="w-full text-left text-sm">{children}</table>;
export const Th = ({ children, right }: { children?: React.ReactNode; right?: boolean }) => <th className={cn("whitespace-nowrap border-b border-border px-2 py-2 font-medium text-muted-foreground", right && "text-right")}>{children}</th>;
export const Td = ({ children, right, className }: { children?: React.ReactNode; right?: boolean; className?: string }) => <td className={cn("border-b border-border px-2 py-2 align-top", right && "text-right tabular-nums", className)}>{children}</td>;

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/40 p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={title} className={cn("mt-10 w-full rounded-lg border border-border bg-background p-5 shadow-xl", wide ? "max-w-4xl" : "max-w-lg")}>
        <div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 hover:bg-muted"><X className="h-4 w-4" /></button></div>
        {children}
      </div>
    </div>
  );
}

export function Select({ value, onChange, children, label, className }: { value: string | number; onChange: (v: string) => void; children: React.ReactNode; label?: string; className?: string }) {
  const el = (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={cn("h-10 rounded-md border border-border bg-background px-3 text-sm", className)}>{children}</select>
  );
  return label ? <label className="block space-y-1.5"><span className="text-sm font-medium">{label}</span>{el}</label> : el;
}

export function Pager({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (o: number) => void }) {
  if (total <= limit) return null;
  return (
    <div className="mt-3 flex items-center justify-between text-sm text-muted-foreground">
      <span>{offset + 1}–{Math.min(offset + limit, total)} of {total}</span>
      <div className="flex gap-2">
        <button className="rounded border border-border px-3 py-1 disabled:opacity-40" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>Previous</button>
        <button className="rounded border border-border px-3 py-1 disabled:opacity-40" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Next</button>
      </div>
    </div>
  );
}

export const money = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toLocaleString(undefined, { style: "decimal", minimumFractionDigits: 2, maximumFractionDigits: 2 }));
export const num = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: d }));
export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(0)}%`);
