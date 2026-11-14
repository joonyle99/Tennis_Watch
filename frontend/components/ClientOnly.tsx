"use client";

import { useSyncExternalStore, type ReactNode } from "react";

const subscribe = () => () => {};

/**
 * 브라우저에서만 내용을 그린다.
 * 모든 화면이 현재 시각과 한국 날짜에 따라 달라지므로, 빌드 시점이나 서버에서 미리 그리면
 * 그때의 시각이 박힌 화면이 나간다.
 */
export function ClientOnly({ children }: { children: ReactNode }) {
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  return mounted ? <>{children}</> : null;
}
