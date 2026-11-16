import { expect, test } from "@playwright/test";

import { login } from "./helpers";

const PAGES = [
  { path: "/", heading: "수집 상태" },
  { path: "/calendar", heading: /에 열리는 예약$/ },
  { path: "/watch", heading: "테니스장" },
  { path: "/settings", heading: "Telegram 알림" },
];

test.beforeEach(async ({ page }) => {
  await login(page);
});

for (const { path, heading } of PAGES) {
  test(`${path} 화면이 휴대폰 너비에서 옆으로 넘치지 않는다`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBe(0);
  });
}

test("아래 탭으로 화면을 오간다", async ({ page }) => {
  await page.goto("/");
  const tabs = page.locator("nav.fixed");
  await expect(tabs).toBeVisible();

  await tabs.getByRole("link", { name: "달력" }).click();
  await expect(page).toHaveURL(/\/calendar$/);
  await expect(tabs.getByRole("link", { name: "달력" })).toHaveAttribute("aria-current", "page");

  await tabs.getByRole("link", { name: "관심 설정" }).click();
  await expect(page.getByRole("heading", { name: "테니스장" })).toBeVisible();
  await tabs.getByRole("link", { name: "시스템" }).click();
  await expect(page.getByRole("heading", { name: "Telegram 알림" })).toBeVisible();
});

test("달력 날짜를 눌러 그날 정보를 본다", async ({ page }) => {
  await page.goto("/calendar");
  const days = page.locator("button[aria-pressed]");
  const last = days.last();
  await last.click();
  await expect(last).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('button[aria-pressed="true"]')).toHaveCount(1);
});
