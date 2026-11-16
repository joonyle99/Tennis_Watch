import { expect, test } from "@playwright/test";

import { login } from "./helpers";

test.beforeEach(async ({ page }) => {
  await login(page);
  await page.goto("/watch");
});

test("시설을 이름과 지역으로 찾는다", async ({ page }) => {
  await expect(page.getByRole("button", { name: /홍은테니스장/ })).toBeVisible();

  await page.getByLabel("시설명 검색").fill("마루");
  await expect(page.getByRole("button", { name: /마루공원/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /홍은테니스장/ })).toHaveCount(0);

  await page.getByLabel("시설명 검색").fill("");
  await page.getByRole("combobox", { name: "지역" }).selectOption("서초구");
  await expect(page.getByRole("button", { name: /잠원한강테니스장/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /마루공원/ })).toHaveCount(0);
});

test("관심 시설을 켜고 끄면 저장된다", async ({ page }) => {
  const toggle = page.getByRole("switch", { name: "홍은테니스장 관심 시설" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await page.reload();
  await expect(page.getByRole("switch", { name: "홍은테니스장 관심 시설" })).toHaveAttribute("aria-checked", "true");

  await page.getByRole("switch", { name: "홍은테니스장 관심 시설" }).click();
  await expect(page.getByRole("switch", { name: "홍은테니스장 관심 시설" })).toHaveAttribute("aria-checked", "false");
});

test("공고명에서 추출한 코트를 확인 처리할 수 있다", async ({ page }) => {
  await page.getByRole("button", { name: /동부도로사업소 테니스장/ }).click();
  await page.getByRole("button", { name: "공고명에서 추출 · 맞으면 확인" }).click();
  await expect(page.getByText("확인됨")).toBeVisible();
});

test("관심 조건을 추가하고 삭제한다", async ({ page }) => {
  await page.getByRole("button", { name: /마루공원/ }).click();
  await expect(page.getByText("기존 조건")).toBeVisible();

  await page.getByLabel("조건 이름").fill("일요일 아침");
  await page.getByRole("button", { name: "일", exact: true }).click();
  await page.getByLabel("시간대 시작").fill("07:00");
  await page.getByLabel("시간대 끝").fill("10:00");
  await page.getByRole("button", { name: "조건 추가" }).click();

  // 시설 항목 안에 조건 항목이 들어 있으므로 가장 안쪽 것을 고른다.
  const rule = page.locator("li").filter({ hasText: "일요일 아침" }).last();
  await expect(rule.getByText(/모든 코트 · 일 · 07:00~10:00 · 오픈 알림 \+ 접수 재개 알림/)).toBeVisible();

  await rule.getByRole("button", { name: "삭제" }).click();
  await expect(page.getByText("일요일 아침")).toHaveCount(0);
  await expect(page.getByText("기존 조건")).toBeVisible();
});

test("시설을 직접 등록하고 삭제한다", async ({ page }) => {
  await page.getByLabel("시설명", { exact: true }).fill("우리동네 테니스장");
  await page.getByLabel("지역", { exact: true }).last().fill("강남구");
  await page.getByRole("button", { name: "등록", exact: true }).click();

  const row = page.getByRole("button", { name: /우리동네 테니스장/ });
  await expect(row).toContainText("수동 등록");
  await expect(page.getByRole("switch", { name: "우리동네 테니스장 관심 시설" })).toHaveAttribute("aria-checked", "true");

  await row.click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "시설 삭제" }).click();
  await expect(page.getByRole("button", { name: /우리동네 테니스장/ })).toHaveCount(0);
});
