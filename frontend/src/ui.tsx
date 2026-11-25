import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

export function useApi<T = any>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(() => {
    if (!path) return;
    setLoading(true);
    api<T>(path).then((d) => { setData(d); setError(null); }).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [path]);
  useEffect(reload, [reload, ...deps]);
  return { data, error, loading, reload, setData };
}

export function Page({ title, actions, children }: { title: string; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">{title}</h1>
        <div className="flex flex-wrap gap-2">{actions}</div>
      </div>
      {children}
    </div>
  );
}

export const Err = ({ e }: { e: string | null }) => (e ? <div className="rounded-lg bg-red-50 text-red-700 text-sm p-2">{e}</div> : null);

export function Score({ v }: { v?: number | null }) {
  if (v == null) return <span className="chip">—</span>;
  const c = v >= 75 ? "bg-emerald-100 text-emerald-800" : v >= 55 ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600";
  return <span className={`inline-block rounded-md px-2 py-0.5 text-sm font-semibold tabular-nums ${c}`}>{Math.round(v)}</span>;
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="card">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-2xl font-semibold tabular-nums mt-1">{value}</div>
      {hint && <div className="text-xs text-slate-400 mt-1">{hint}</div>}
    </div>
  );
}

export function Bar({ value, max, label, right }: { value: number; max: number; label: string; right?: string }) {
  return (
    <div className="text-sm">
      <div className="flex justify-between"><span>{label}</span><span className="tabular-nums text-slate-500">{right ?? value}</span></div>
      <div className="h-2 bg-slate-100 rounded"><div className="h-2 bg-indigo-500 rounded" style={{ width: `${max ? (100 * value) / max : 0}%` }} /></div>
    </div>
  );
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true); setErr(null); setMsg(null);
    try { await fn(); if (ok) setMsg(ok); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return { busy, msg, err, run };
}

export const Flash = ({ msg, err }: { msg: string | null; err: string | null }) => (
  <>{msg && <div className="rounded-lg bg-emerald-50 text-emerald-800 text-sm p-2">{msg}</div>}<Err e={err} /></>
);
