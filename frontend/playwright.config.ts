import { defineConfig, devices } from "@playwright/test";

// 화면 E2E 테스트. 실제 사이트나 Telegram에는 요청하지 않는다(backend/tests/e2e_server.py).
//   npm run e2e
const BACKEND_PORT = 8100;
const FRONTEND_PORT = 3100;
export const PASSWORD = "e2e-password";

export default defineConfig({
  testDir: "./e2e",
  // 테스트들이 DB 하나를 함께 쓰므로 차례로 실행한다.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
    trace: "off",
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /mobile\.spec\.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
  ],
  webServer: [
    {
      command: `${process.env.E2E_PYTHON ?? "python3"} -m tests.e2e_server`,
      cwd: "../backend",
      url: `http://127.0.0.1:${BACKEND_PORT}/api/health`,
      env: { E2E_BACKEND_PORT: String(BACKEND_PORT), E2E_PASSWORD: PASSWORD },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run build && npx next start -H 127.0.0.1 -p ${FRONTEND_PORT}`,
      url: `http://127.0.0.1:${FRONTEND_PORT}/login`,
      env: { BACKEND_URL: `http://127.0.0.1:${BACKEND_PORT}` },
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
