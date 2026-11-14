"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const ITEMS = [
  { href: "/", label: "대시보드" },
  { href: "/calendar", label: "달력" },
  { href: "/watch", label: "관심 설정" },
  { href: "/settings", label: "시스템" },
];

export function Nav() {
  const pathname = usePathname();
  if (pathname === "/login") return null;
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-stone-200 bg-white/90 backdrop-blur dark:border-stone-800 dark:bg-stone-950/90">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-6 px-4">
          <Link href="/" className="flex items-center gap-2 font-bold">
            <span aria-hidden className="h-3 w-3 rounded-full bg-lime-400 ring-2 ring-emerald-700" />
            Tennis Watch
          </Link>
          <nav className="hidden gap-1 sm:flex">
            {ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive(item.href) ? "page" : undefined}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
                  isActive(item.href)
                    ? "bg-emerald-700 text-white"
                    : "text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-stone-800"
                }`}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>
      {/* 휴대폰에서는 엄지로 닿는 아래쪽 탭 */}
      <nav className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-4 border-t border-stone-200 bg-white pb-[env(safe-area-inset-bottom)] sm:hidden dark:border-stone-800 dark:bg-stone-950">
        {ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            aria-current={isActive(item.href) ? "page" : undefined}
            className={`flex h-14 items-center justify-center text-sm font-medium ${
              isActive(item.href)
                ? "text-emerald-700 dark:text-emerald-400"
                : "text-stone-500 dark:text-stone-400"
            }`}
          >
            <span className={isActive(item.href) ? "border-b-2 border-emerald-700 pb-0.5 dark:border-emerald-400" : ""}>
              {item.label}
            </span>
          </Link>
        ))}
      </nav>
    </>
  );
}
