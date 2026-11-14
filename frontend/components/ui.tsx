"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

import type { Tone } from "@/lib/format";

const TONES: Record<Tone, string> = {
  good: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  info: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  warn: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  bad: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  muted: "bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-300",
};

export function Badge({ tone = "muted", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function Card({
  title,
  hint,
  action,
  children,
}: {
  title?: string;
  hint?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 border-b border-stone-200 px-4 py-3 dark:border-stone-800">
          <div className="min-w-0">
            <h2 className="font-semibold">{title}</h2>
            {hint && <p className="mt-0.5 text-xs text-stone-500 dark:text-stone-400">{hint}</p>}
          </div>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" };

export function Button({ variant = "ghost", className = "", ...props }: ButtonProps) {
  const styles = {
    primary: "bg-emerald-700 text-white hover:bg-emerald-800 border-transparent",
    ghost:
      "border-stone-300 bg-white hover:bg-stone-100 dark:border-stone-700 dark:bg-stone-900 dark:hover:bg-stone-800",
    danger: "border-rose-300 text-rose-700 hover:bg-rose-50 dark:border-rose-900 dark:text-rose-300 dark:hover:bg-rose-950",
  }[variant];
  return (
    <button
      type="button"
      {...props}
      className={`inline-flex min-h-9 shrink-0 items-center justify-center gap-1 rounded-lg border px-3 text-sm font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
    />
  );
}

/** 너비를 따로 정하는 입력 상자용 */
export const inputBase =
  "min-h-9 rounded-lg border border-stone-300 bg-white px-2.5 text-sm dark:border-stone-700 dark:bg-stone-950";
export const inputClass = `${inputBase} w-full`;

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-stone-700 dark:text-stone-300">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-stone-500 dark:text-stone-400">{hint}</span>}
    </label>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
        checked ? "bg-emerald-600" : "bg-stone-300 dark:bg-stone-700"
      }`}
    >
      <span
        className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-5" : ""
        }`}
      />
    </button>
  );
}

export function Note({ tone = "muted", children }: { tone?: Tone; children: ReactNode }) {
  const styles: Record<Tone, string> = {
    good: "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
    info: "border-sky-300 bg-sky-50 text-sky-900 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-200",
    warn: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200",
    bad: "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200",
    muted: "border-stone-200 bg-stone-50 text-stone-600 dark:border-stone-800 dark:bg-stone-950 dark:text-stone-400",
  };
  return <p className={`rounded-lg border px-3 py-2 text-sm ${styles[tone]}`}>{children}</p>;
}

/** 불러오는 중, 오류, 빈 목록을 한곳에서 처리한다. */
export function Loadable<T>({
  state,
  empty,
  children,
}: {
  state: { data: T | null; error: string | null; loading: boolean };
  empty?: string;
  children: (data: T) => ReactNode;
}) {
  if (state.error && state.data === null) return <Note tone="bad">불러오지 못했습니다: {state.error}</Note>;
  if (state.data === null) return <p className="text-sm text-stone-500">불러오는 중…</p>;
  if (empty && Array.isArray(state.data) && state.data.length === 0) {
    return <p className="text-sm text-stone-500 dark:text-stone-400">{empty}</p>;
  }
  return <>{children(state.data)}</>;
}

export function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex min-h-9 shrink-0 items-center rounded-lg bg-emerald-700 px-3 text-sm font-medium text-white hover:bg-emerald-800"
    >
      {children}
    </a>
  );
}
