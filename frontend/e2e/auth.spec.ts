import { expect, test } from "@playwright/test";

import { PASSWORD } from "../playwright.config";

test("로그인하지 않으면 로그인 화면으로 가고, 비밀번호가 맞아야 들어간다", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel("비밀번호").fill("wrong-password");
  await page.getByRole("button", { name: "들어가기" }).click();
  await expect(page.getByText("비밀번호가 맞지 않습니다")).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel("비밀번호").fill(PASSWORD);
  await page.getByRole("button", { name: "들어가기" }).click();
  await expect(page.getByRole("heading", { name: "수집 상태" })).toBeVisible();

  const session = (await page.context().cookies()).find((cookie) => cookie.name === "tw_session");
  expect(session?.httpOnly).toBe(true);
});

test("로그아웃하면 다시 막힌다", async ({ page }) => {
  await page.request.post("/api/auth/login", { data: { password: PASSWORD } });
  await page.goto("/settings");
  await page.getByRole("button", { name: "로그아웃" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goto("/watch");
  await expect(page).toHaveURL(/\/login$/);
  expect((await page.request.get("/api/facilities")).status()).toBe(401);
});
