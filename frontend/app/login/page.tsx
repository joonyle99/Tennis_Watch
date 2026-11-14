"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Button, Field, inputClass, Note } from "@/components/ui";
import { api } from "@/lib/api";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // 이미 로그인했거나 비밀번호가 설정되지 않았으면 바로 대시보드로 보낸다.
    api<{ authenticated: boolean }>("/auth/status")
      .then((s) => s.authenticated && window.location.replace("/"))
      .catch(() => undefined);
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/login", { method: "POST", body: { password } });
      window.location.replace("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "로그인하지 못했습니다");
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-16 max-w-sm rounded-xl border border-stone-200 bg-white p-6 dark:border-stone-800 dark:bg-stone-900">
      <h1 className="mb-4 flex items-center gap-2 text-lg font-bold">
        <span aria-hidden className="h-3 w-3 rounded-full bg-lime-400 ring-2 ring-emerald-700" />
        Tennis Watch
      </h1>
      <form onSubmit={submit} className="space-y-3">
        <Field label="비밀번호">
          <input
            type="password"
            autoFocus
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClass}
          />
        </Field>
        {error && <Note tone="bad">{error}</Note>}
        <Button type="submit" variant="primary" disabled={busy || !password} className="w-full">
          {busy ? "확인 중…" : "들어가기"}
        </Button>
      </form>
    </div>
  );
}
