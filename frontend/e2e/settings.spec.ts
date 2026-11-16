import { expect, test } from "@playwright/test";

import { card, login } from "./helpers";

test.beforeEach(async ({ page }) => {
  await login(page);
  await page.goto("/settings");
});

test("Telegram 연결 테스트 결과를 알려 준다", async ({ page }) => {
  await page.getByRole("button", { name: "연결 테스트" }).click();
  await expect(page.getByText("테스트 메시지를 보냈습니다 (@e2e_test_bot). Telegram을 확인하세요.")).toBeVisible();
});

test("알림을 끄고 켠다", async ({ page }) => {
  const toggle = page.getByRole("switch", { name: "알림 보내기" });
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await toggle.click();
  await expect(page.getByText("알림을 껐습니다")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("switch", { name: "알림 보내기" })).toHaveAttribute("aria-checked", "false");
  await page.getByRole("switch", { name: "알림 보내기" }).click();
  await expect(page.getByText("알림을 켰습니다")).toBeVisible();
});

test("오픈 알림 시점을 추가하고 삭제한다", async ({ page }) => {
  const offsets = card(page, "예약 오픈 알림 시점");
  await expect(offsets.getByText("1일 전")).toBeVisible();
  await expect(offsets.getByText("10분 전")).toBeVisible();

  await offsets.getByLabel("알림 시점 값").fill("30");
  await offsets.getByRole("button", { name: "추가" }).click();
  await expect(offsets.getByText("30분 전")).toBeVisible();
  await page.reload();
  await expect(offsets.getByText("30분 전")).toBeVisible();

  await offsets.getByRole("button", { name: "30분 전 삭제" }).click();
  await expect(offsets.getByText("30분 전")).toHaveCount(0);
});

test("수집 주기를 바꾸고, 범위를 벗어난 값은 거절한다", async ({ page }) => {
  const collect = card(page, "자동 수집");
  await collect.getByLabel("수집 주기 (분)").fill("10");
  await collect.getByRole("button", { name: "저장" }).click();
  await expect(page.getByText("저장했습니다")).toBeVisible();
  await page.reload();
  await expect(collect.getByLabel("수집 주기 (분)")).toHaveValue("10");

  await collect.getByLabel("수집 주기 (분)").fill("5");
  await collect.getByRole("button", { name: "저장" }).click();
  await expect(collect.getByLabel("수집 주기 (분)")).toHaveValue("5");
});

test("자동 규칙과 수동 규칙을 구분해 보여 준다", async ({ page }) => {
  const rules = card(page, "예약 오픈 규칙");
  const rolling = rules.locator("li").filter({ hasText: "이용일 14일 전 14:00" });
  await expect(rolling.getByText("자동")).toBeVisible();
  await expect(rolling.getByText("검증됨")).toBeVisible();
  await expect(rolling.getByText("6개 공고")).toBeVisible(); // 같은 규칙은 한 줄로 합친다
  await expect(rolling.getByRole("button", { name: "삭제" })).toHaveCount(0); // 자동 규칙은 지울 수 없다

  const monthly = rules.locator("li").filter({ hasText: "추정 규칙 예시" });
  await expect(monthly.getByText(/매월 \d+일 00:00/)).toBeVisible();
  await expect(monthly.getByText("수동")).toBeVisible();
  await expect(monthly.getByText("추정", { exact: true })).toBeVisible();
});

test("추정 규칙을 등록하면 목록과 대시보드의 오픈 예정에 나타난다", async ({ page }) => {
  const rules = card(page, "예약 오픈 규칙");
  await rules.getByLabel("시설").selectOption({ label: "동부도로사업소 테니스장" });
  await rules.getByLabel("매월 며칠").fill("25");
  await rules.getByLabel("오픈 시각").fill("09:30");
  await rules.getByLabel("대상 설명").fill("다음 달 1~15일 이용분");
  await rules.getByRole("button", { name: "규칙 등록" }).click();

  const added = rules.locator("li").filter({ hasText: "매월 25일 09:30" });
  await expect(added.getByText("추정")).toBeVisible();
  await expect(added.getByText("다음 달 1~15일 이용분")).toBeVisible();

  await added.getByRole("button", { name: "삭제" }).click();
  await expect(rules.getByText("매월 25일 09:30")).toHaveCount(0);
});

test("수집 기록을 보여 준다", async ({ page }) => {
  const logs = card(page, "수집 기록");
  await expect(logs.getByRole("cell", { name: "목록" }).first()).toBeVisible();
  await expect(logs.getByText("성공").first()).toBeVisible();
});
