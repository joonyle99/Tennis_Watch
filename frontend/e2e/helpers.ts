import { expect, type Page } from "@playwright/test";

import { PASSWORD } from "../playwright.config";

/** 로그인 화면을 거치지 않고 세션을 만든다. */
export async function login(page: Page) {
  const response = await page.request.post("/api/auth/login", { data: { password: PASSWORD } });
  expect(response.ok()).toBeTruthy();
}

export function card(page: Page, title: string) {
  return page.locator("section").filter({ has: page.getByRole("heading", { name: title, exact: true }) });
}
