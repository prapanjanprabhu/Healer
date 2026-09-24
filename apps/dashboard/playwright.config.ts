import { defineConfig, devices } from "@playwright/test";

// Runs against the real dev stack (docker compose up), not a mocked
// backend — the dashboard has no meaning without a real Control Plane
// behind it. Start the stack yourself before running `npm run test:e2e`;
// this config does not start it for you (a real deploy/health-check flow
// needs a real Agent, which nothing here can spin up automatically).
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
