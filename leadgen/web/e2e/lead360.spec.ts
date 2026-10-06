import { expect, test } from "@playwright/test";
import type { Page, Request } from "@playwright/test";

import { LEAD_ID, REVIEW_ID, brief, lead360, leads, me, reviews } from "./fixtures";

interface Recorded {
  method: string;
  path: string;
  body: unknown;
  headers: Record<string, string>;
}

/** Serve the API from fixtures and record every call the SPA makes. */
async function mockApi(page: Page): Promise<Recorded[]> {
  const calls: Recorded[] = [];
  await page.route("**/api/**", async (route) => {
    const request: Request = route.request();
    const url = new URL(request.url());
    const headers = request.headers();
    calls.push({ method: request.method(), path: url.pathname + url.search, body: request.postDataJSON(), headers });
    const roles = (headers["x-dev-roles"] ?? "admin").split(",");
    const json = (body: unknown, status = 200) => route.fulfill({ status, json: body });

    if (url.pathname === "/api/v1/me") return json(me(roles));
    if (url.pathname === "/api/v1/leads") return json(leads);
    if (url.pathname === `/api/v1/leads/${LEAD_ID}` && request.method() === "GET") return json(lead360);
    if (url.pathname === `/api/v1/leads/${LEAD_ID}` && request.method() === "PATCH") {
      return json({ id: LEAD_ID, updated: true });
    }
    if (url.pathname === `/api/v1/leads/${LEAD_ID}/brief`) return json(brief);
    if (url.pathname === "/api/v1/review") {
      if (!roles.includes("admin") && !roles.includes("analyst")) {
        return json({ status: 403, detail: "missing permission", details: { missing: ["entities:merge"] } }, 403);
      }
      return json(reviews);
    }
    if (url.pathname === `/api/v1/review/${REVIEW_ID}`) return json({ id: REVIEW_ID, decision: "accept" });
    return json({ status: 404, detail: "not mocked" }, 404);
  });
  return calls;
}

let consoleErrors: string[] = [];

test.beforeEach(async ({ page }) => {
  consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(err.message));
});

test.afterEach(() => {
  // Includes "Refused to ... because it violates the following Content Security Policy directive".
  expect(consoleErrors).toEqual([]);
});

test("worklist to Lead 360: score explanation, provenance, signals and graph", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/");

  await expect(page).toHaveURL(/\/leads$/);
  await expect(page.getByRole("heading", { name: "Leads" })).toBeVisible();
  await expect(page.getByRole("row")).toHaveCount(3); // header + 2 leads
  await page.getByRole("link", { name: "Northwind Analytics" }).click();

  await expect(page).toHaveURL(new RegExp(`/leads/${LEAD_ID}$`));
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Northwind Analytics");
  await expect(page.getByText("Funding 9 days ago: Raised Series B")).toBeVisible();
  await expect(page.getByRole("img", { name: "Fit: 88.0 of 100" })).toBeVisible();

  // Golden record with provenance and the losing alternative value.
  const industry = page.getByRole("row", { name: /Industry/ });
  await expect(industry).toContainText("Software Development");
  await expect(industry).toContainText("LinkedIn company page (ScrapeBadger)");
  await industry.getByText("1 other value").click();
  await expect(industry).toContainText("IT Services");

  // Signals: https links are rendered, javascript: URLs are not.
  await expect(page.getByRole("link", { name: "Northwind Analytics raises Series B" })).toHaveAttribute(
    "href",
    "https://news.example/northwind-series-b",
  );
  await expect(page.getByText("Viewed /pricing")).toBeVisible();
  await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);

  // Relationship graph: three entities, two relationships.
  const graph = page.getByRole("img", { name: /Relationship graph with 3 entities and 2 relationships/ });
  await expect(graph).toBeVisible();
  await expect(graph.locator("circle")).toHaveCount(3);

  // Contact details are shown to pii:read holders, with the audit notice.
  await expect(page.getByText("jordan.lee@northwind-analytics.example")).toBeVisible();
  await expect(page.getByText("Viewing contact details is recorded in the audit log.")).toBeVisible();

  // Status change is a PATCH with exactly the new status.
  await page.getByLabel("Status").selectOption("working");
  await expect.poll(() => calls.find((c) => c.method === "PATCH")?.body).toEqual({ status: "working" });

  // AI brief on demand.
  await page.getByRole("button", { name: "Generate brief" }).click();
  await expect(page.getByText(brief.summary)).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh brief" })).toBeVisible();
});

test("review queue: accepting a match posts the decision", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/review");

  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();
  await expect(page.getByText("88.1%")).toBeVisible();
  await expect(page.getByText("names match (similarity 0.97)")).toBeVisible();
  await page.getByRole("button", { name: "Same entity: merge" }).click();

  await expect(page.getByText("1 decision recorded.")).toBeVisible();
  await expect(page.getByText("Nothing to review.")).toBeVisible();
  expect(calls.find((c) => c.method === "POST")).toMatchObject({
    path: `/api/v1/review/${REVIEW_ID}`,
    body: { decision: "accept" },
  });
});

test("dev persona picker changes identity headers and hides what the role cannot use", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/leads");
  await expect(page.getByRole("link", { name: "Review queue" })).toBeVisible();

  await page.getByLabel("Acting as").selectOption("viewer");
  await expect(page.getByRole("link", { name: "Review queue" })).toHaveCount(0);
  const last = calls.filter((c) => c.path === "/api/v1/me").at(-1);
  expect(last?.headers["x-dev-roles"]).toBe("viewer");

  await page.getByRole("link", { name: "Northwind Analytics" }).click();
  await expect(page.getByRole("button", { name: "Generate brief" })).toHaveCount(0);
  await expect(page.getByLabel("Status")).toHaveCount(0);
});

test("phone width: no horizontal page scroll", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 375, height: 800 });
  for (const path of ["/leads", `/leads/${LEAD_ID}`, "/review"]) {
    await page.goto(path);
    await expect(page.locator("main h1")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
});
