import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests for the things unit tests cannot see: that a page is genuinely
 * server-rendered in the right direction, that the URL is the only state, and
 * that the site works with JavaScript switched off.
 *
 * Hermetic on purpose. The app talks to a stub API (tests/e2e/stub-api.mjs)
 * rather than the real one, so the suite needs no Postgres, Meilisearch or
 * Python and cannot fail because the catalogue changed. The API is tested
 * separately.
 */
const WEB_PORT = 3210;
const STUB_PORT = 8787;

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: /.*\.spec\.ts/,
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "line" : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `node tests/e2e/stub-api.mjs`,
      port: STUB_PORT,
      env: { STUB_PORT: String(STUB_PORT) },
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      // A production build, not `next dev`, for two reasons: it is what actually
      // ships, and Next refuses to run a second dev server from the same
      // directory — so `pnpm dev` running in another terminal would otherwise
      // break the suite.
      command: `npx next build && npx next start --port ${WEB_PORT}`,
      port: WEB_PORT,
      env: { API_INTERNAL_URL: `http://localhost:${STUB_PORT}` },
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
      stdout: "ignore",
    },
  ],
});
