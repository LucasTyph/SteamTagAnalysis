import { defineConfig, devices } from "@playwright/test";

// Browser smoke test: serves the production build (npm run build first) and checks
// that every page loads its data, runs its DuckDB queries and draws its charts
// without console errors.
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 30_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  // CI installs Playwright's Chromium; locally, the Edge that ships with Windows is enough.
  use: { baseURL: "http://localhost:4173/", channel: process.env.CI ? undefined : "msedge" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run preview -- --port 4173 --strictPort",
    url: "http://localhost:4173/",
    reuseExistingServer: !process.env.CI,
  },
});
