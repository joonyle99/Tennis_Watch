"use client";

import { useEffect, useState } from "react";

/** 남은 시간 표시를 위해 주기적으로 갱신되는 현재 시각. */
export function useNow(intervalMs = 30000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}
