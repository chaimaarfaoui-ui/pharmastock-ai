"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Page, type Row } from "./api";

export function useFetch<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const load = useCallback(async () => {
    setLoading(true);
    try { setData(await fnRef.current()); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Request failed"); }
    finally { setLoading(false); }
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); }, deps);
  return { data, error, loading, reload: load };
}

export const useMedicines = () => useFetch(() => api<Page<Row>>("/medicines?limit=200"), []);
export const useSuppliers = () => useFetch(() => api<Page<Row>>("/suppliers?limit=200"), []);
export const useCategories = () => useFetch(() => api<Row[]>("/categories"), []);

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true); setError(null);
    try { return await fn(); }
    catch (e) { setError(e instanceof Error ? e.message : "Action failed"); }
    finally { setBusy(false); }
  }, []);
  return { busy, error, setError, run };
}
