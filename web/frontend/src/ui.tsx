import { useEffect, useState, type ReactNode } from "react";
import type { Severity, Verdict } from "./api";

export function useHashRoute(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("?")[0].split("/").filter(Boolean).map(decodeURIComponent);
  const [parts, setParts] = useState(read);
  useEffect(() => {
    const on = () => setParts(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return parts;
}

export function hashParams(): URLSearchParams {
  return new URLSearchParams(window.location.hash.split("?")[1] ?? "");
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): { data?: T; error?: string; loading: boolean } {
  const [state, setState] = useState<{ data?: T; error?: string; loading: boolean }>({ loading: true });
  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true }));
    fn()
      .then((data) => live && setState({ data, loading: false }))
      .catch((e: unknown) => live && setState({ error: String(e), loading: false }));
    return () => {
      live = false;
    };
  }, deps);
  return state;
}

export function Loading({ state, children }: { state: { error?: string; loading: boolean }; children: ReactNode }) {
  if (state.error) return <div className="error">Could not load: {state.error}</div>;
  if (state.loading) return <div className="muted">Loading...</div>;
  return <>{children}</>;
}

export function Sev({ s }: { s: Severity }) {
  return <span className={`sev ${s}`}>{s}</span>;
}

export function VerdictTag({ v }: { v: Verdict | string | null }) {
  return <span className={`verdict ${v ?? "none"}`}>{v ?? "-"}</span>;
}

export function Card({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className={`card ${tone ?? ""}`}>
      <span className="muted">{label}</span>
      <b>{value}</b>
    </div>
  );
}

export function Bar({ parts }: { parts: { value: number; tone: string; label: string }[] }) {
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  return (
    <div className="bar" title={parts.map((p) => `${p.label}: ${p.value}`).join(", ")}>
      {parts.map((p) => (
        <span key={p.label} className={p.tone} style={{ width: `${(100 * p.value) / total}%` }} />
      ))}
    </div>
  );
}

export const pct = (v: number | null | undefined, digits = 1) => (v === null || v === undefined ? "-" : `${(100 * v).toFixed(digits)}%`);
export const usd = (v: number | null | undefined) => (v === null || v === undefined ? "unknown" : `$${v.toFixed(4)}`);
export const ms = (v: number | null | undefined) => (v === null || v === undefined ? "-" : `${v.toFixed(1)} ms`);
export const when = (iso: string) => new Date(iso).toLocaleString();
