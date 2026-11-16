import { expect, test } from "@playwright/test";

import { card, login } from "./helpers";

test.beforeEach(async ({ page }) => {
  await login(page);
  await page.goto("/calendar");
});

test("오늘이 선택되어 있고 그날의 오픈과 이용분 공고를 보여 준다", async ({ page }) => {
  await expect(page.locator('button[aria-pressed="true"]')).toHaveCount(1);
  await expect(page.getByRole("heading", { name: /에 열리는 예약$/ })).toBeVisible();

  const notices = page.locator("section").filter({ has: page.getByRole("heading", { name: /이용분 공고$/ }) });
  await expect(notices.getByText("마루공원 테니스장 1면", { exact: true })).toBeVisible();
  await expect(notices.getByText("접수중").first()).toBeVisible();
});

test("아직 열리지 않은 날짜는 접수 전으로, 오픈 시각과 함께 보여 준다", async ({ page }) => {
  // 마루공원은 14일 전에 열리므로 20일 뒤 날짜는 아직 열리지 않았다.
  const target = new Date(Date.now() + 9 * 3600 * 1000 + 20 * 86400 * 1000);
  const today = new Date(Date.now() + 9 * 3600 * 1000);
  if (target.getUTCMonth() !== today.getUTCMonth()) await page.getByRole("button", { name: "다음 달" }).click();
  await page.getByRole("button", { name: new RegExp(`^${target.getUTCMonth() + 1}월 ${target.getUTCDate()}일 `) }).click();

  const notices = page.locator("section").filter({ has: page.getByRole("heading", { name: /이용분 공고$/ }) });
  const row = notices.locator("li").filter({ hasText: "마루공원 테니스장 1면" }).first();
  await expect(row.getByText("접수 전")).toBeVisible();
  await expect(row.getByText(/14:00 오픈/)).toBeVisible();
});

test("시설 필터가 공고 목록을 좁힌다", async ({ page }) => {
  const notices = page.locator("section").filter({ has: page.getByRole("heading", { name: /이용분 공고$/ }) });
  await expect(notices.getByText(/마루공원 테니스장/).first()).toBeVisible();

  await page.getByLabel("시설", { exact: true }).first().selectOption({ label: "동부도로사업소 테니스장" });
  await expect(notices.getByText(/마루공원 테니스장/)).toHaveCount(0);
  await expect(page.getByLabel("코트", { exact: true }).first()).toBeVisible(); // 시설을 고르면 코트 필터가 생긴다
});

test("직접 확인한 시간대를 적고 지울 수 있다", async ({ page }) => {
  const memo = card(page, "직접 확인한 시간대");
  await expect(memo.getByText("적어 둔 시간대가 없습니다.")).toBeVisible();

  await memo.getByLabel("시설").selectOption({ label: "마루공원" });
  await memo.getByLabel("시작").fill("18:00");
  await memo.getByLabel("종료").fill("20:00");
  await memo.getByLabel("메모").fill("사이트에서 직접 확인");
  await memo.getByRole("button", { name: /기록$/ }).click();

  const row = memo.locator("li").filter({ hasText: "18:00~20:00" });
  await expect(row.getByText("예약 가능")).toBeVisible();
  await expect(row.getByText(/사이트에서 직접 확인/)).toBeVisible();

  await page.reload();
  await expect(memo.locator("li").filter({ hasText: "18:00~20:00" })).toBeVisible(); // 저장되어 있다

  await memo.getByRole("button", { name: "지우기" }).click();
  await expect(memo.getByText("적어 둔 시간대가 없습니다.")).toBeVisible();
});

test("종료가 시작보다 빠르면 저장하지 않고 이유를 알려 준다", async ({ page }) => {
  const memo = card(page, "직접 확인한 시간대");
  await memo.getByLabel("시작").fill("20:00");
  await memo.getByLabel("종료").fill("18:00");
  await memo.getByRole("button", { name: /기록$/ }).click();
  await expect(memo.getByText(/start_time이 end_time보다/)).toBeVisible();
});
