import type { Metadata, Viewport } from "next";

import { ClientOnly } from "@/components/ClientOnly";
import { Nav } from "@/components/Nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "Tennis Watch",
  description: "테니스 코트 예약 오픈 일정과 접수 상태 모니터링",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className="h-full antialiased">
      <body className="min-h-full bg-stone-100 text-stone-900 dark:bg-stone-950 dark:text-stone-100">
        <Nav />
        <main className="mx-auto max-w-5xl px-4 pt-5 pb-24 sm:pb-10">
          <ClientOnly>{children}</ClientOnly>
        </main>
      </body>
    </html>
  );
}
