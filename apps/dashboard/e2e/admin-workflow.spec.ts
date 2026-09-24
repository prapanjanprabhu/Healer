import { expect, test } from "@playwright/test";

// Covers the main Administrator workflow end to end against the REAL
// running dev stack (dashboard + Control Plane), the same way every prior
// phase of this project was verified — no mocked backend. What it does
// NOT cover: an actual deploy/scale/health-check/rollback round trip,
// since those need a real connected Agent on a real target server, which
// this suite can't provision for itself. That path is covered by the
// backend's own hermetic test suite (services/control-plane/tests) plus
// this project's manual live-verification sessions each phase. This spec
// proves the UI itself — every screen a real Administrator uses to get
// there — genuinely works: login, registering a server, describing an
// application, and the account/user/audit management screens.

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "phase12-verify@healer.test";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "Phase12Verify!2026";

test.describe.configure({ mode: "serial" });

test("an administrator can sign in, see the overview, and reach every main screen", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(ADMIN_EMAIL);
  await page.getByLabel(/password/i).fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { name: /overview/i })).toBeVisible();

  for (const [label, heading] of [
    ["Servers", /servers/i],
    ["Applications", /applications/i],
    ["Deployments", /deployments/i],
    ["Health", /health/i],
    ["Certificates", /certificates/i],
    ["Settings", /settings/i],
  ] as const) {
    await page.getByRole("link", { name: label }).click();
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  }
});

test("an administrator can register a server", async ({ page }) => {
  await login(page);

  await page.goto("/servers/new");
  const hostname = `e2e-${Date.now()}.internal`;
  await page.getByLabel("Name", { exact: true }).fill("E2E Test Server");
  await page.getByLabel(/hostname/i).fill(hostname);
  await page.getByRole("button", { name: /register server/i }).click();

  await expect(page).toHaveURL(/\/servers\/[0-9a-f-]+$/);
  await expect(page.getByText(hostname)).toBeVisible();
});

test("an administrator can describe a new application and see its detail page", async ({ page }) => {
  await login(page);

  await page.goto("/applications/new");
  const name = `E2E App ${Date.now()}`;
  await page.getByLabel(/^name$/i).fill(name);
  await page.getByLabel(/target server/i).selectOption({ index: 1 });
  await page.getByLabel(/python executable/i).fill("C:\\Python\\python.exe");
  await page.getByLabel(/folder path|git url/i).fill("C:\\HealerTest\\e2e");
  await page.getByLabel(/wsgi module/i).fill("erp.wsgi");
  await page.getByLabel(/settings module/i).fill("erp.settings");
  await page.getByRole("button", { name: /save application/i }).click();

  await expect(page).toHaveURL(/\/applications\/[0-9a-f-]+$/);
  await expect(page.getByText(name)).toBeVisible();
  await expect(page.getByText(/scale/i).first()).toBeVisible();
});

test("an administrator can create a user and see it in the audit log", async ({ page }) => {
  await login(page);

  await page.goto("/users");
  const email = `e2e-user-${Date.now()}@healer.test`;
  await page.getByLabel(/^email$/i).fill(email);
  await page.getByLabel(/^password$/i).fill("a-strong-e2e-password");
  await page.getByRole("button", { name: /create user/i }).click();

  await expect(page.getByText(email)).toBeVisible();

  await page.goto("/audit-log");
  await expect(page.getByText("user.create").first()).toBeVisible();
});

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(ADMIN_EMAIL);
  await page.getByLabel(/password/i).fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL("/");
}
