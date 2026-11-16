import { expect, test } from "@playwright/test";

import { card, login } from "./helpers";

test.beforeEach(async ({ page }) => {
  await login(page);
  await page.goto("/");
});

test("수집 상태와 관심 시설을 보여 준다", async ({ page }) => {
  const status = card(page, "수집 상태");
  await expect(status.getByText("마지막 정상 수집")).toBeVisible();
  await expect(status.getByText("동부도로사업소 테니스장, 마루공원")).toBeVisible();
  await expect(status.getByText("없음", { exact: true })).toBeVisible(); // 연속 실패 없음
});

test("오픈 예정을 시각 순으로, 같은 시각은 한 줄로 묶어 보여 준다", async ({ page }) => {
  const openings = card(page, "예약 오픈 예정");
  // 마루공원은 공고 6개가 같은 시각에 열리므로 한 줄에 "6개 공고"로 나온다.
  await expect(openings.getByText("6개 공고").first()).toBeVisible();
  await expect(openings.getByText("동부 도로사업소 테니스장 A코트 주말 및 공휴일 다음 회차")).toBeVisible();
  // 수동으로 등록한 추정 규칙은 "추정" 표시가 붙는다.
  await expect(openings.locator("li").filter({ hasText: "추정 규칙 예시" }).getByText("추정", { exact: true })).toBeVisible();

  const link = openings.getByRole("link", { name: "예약 사이트" }).first();
  await expect(link).toHaveAttribute("href", /yeyak\.seoul\.go\.kr\/web\/reservation\/selectReservView\.do\?rsv_svc_id=/);
  await expect(link).toHaveAttribute("target", "_blank");
});

test("접수중인 공고만 시설별로 보여 준다", async ({ page }) => {
  const open = card(page, "지금 접수중인 공고");
  await expect(open.getByText("동부 도로사업소 테니스장 A코트 평일주간 이번 회차")).toBeVisible();
  await expect(open.getByText("마루공원 테니스장 3면 (조명)")).toBeVisible();
  await expect(open.getByText("이용일 14일 전 14시 오픈").first()).toBeVisible();
  // 예약마감 공고와 비관심 시설의 공고는 나오지 않는다.
  await expect(open.getByText("평일야간 이번 회차")).toHaveCount(0);
  await expect(open.getByText("홍은테니스장")).toHaveCount(0);
});

test("접수 재개 기록을 보여 준다", async ({ page }) => {
  const reopened = card(page, "최근 접수 재개");
  await expect(reopened.getByText("동부 도로사업소 테니스장 A코트 주말 및 공휴일 이번 회차")).toBeVisible();
  await expect(reopened.getByText("예약마감 → 접수중")).toBeVisible();
});

test("지금 수집을 누르면 수집하고 결과를 알려 준다", async ({ page }) => {
  await page.getByRole("button", { name: "지금 수집" }).click();
  await expect(page.getByText(/수집 완료 \(공고 12건 확인\)/)).toBeVisible();
});

test("시각을 한국시간으로 표시한다", async ({ page }) => {
  // 마루공원은 한국시간 14:00에 열린다. UTC(05:00)로 나오면 안 된다.
  const openings = card(page, "예약 오픈 예정");
  await expect(openings.getByText(/\d+월 \d+일 \([월화수목금토일]\) 14:00/).first()).toBeVisible();
  await expect(openings.getByText(/ 05:00/)).toHaveCount(0);
});
