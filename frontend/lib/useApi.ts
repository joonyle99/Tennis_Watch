"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";

/** 경로의 데이터를 불러온다. refreshMs를 주면 그 간격으로 다시 불러온다. path가 null이면 쉬고 있는다. */
export function useApi<T>(path: string | null, refreshMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const latest = useRef(0);

  const reload = useCallback(async () => {
    if (path === null) return;
    const ticket = ++latest.current;
    try {
      const result = await api<T>(path);
      if (ticket !== latest.current) return; // 더 늦게 보낸 요청의 응답만 쓴다
      setData(result);
      setError(null);
    } catch (e) {
      if (ticket !== latest.current) return;
      setError(e instanceof Error ? e.message : "알 수 없는 오류");
    } finally {
      if (ticket === latest.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    if (path === null) return;
    setLoading(true);
    void reload();
    if (!refreshMs) return;
    const timer = setInterval(() => void reload(), refreshMs);
    return () => clearInterval(timer);
  }, [path, refreshMs, reload]);

  return { data, error, loading, reload };
}
