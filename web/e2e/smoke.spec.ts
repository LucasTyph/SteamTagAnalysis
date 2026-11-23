import { type Page, expect, test } from "@playwright/test";

// Fail on anything the page logs as an error or throws.
function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));
  return errors;
}

test.describe("every page loads its data", () => {
  let errors: string[];
  test.beforeEach(({ page }) => {
    errors = watchErrors(page);
  });
  test.afterEach(() => {
    expect(errors, "console errors").toEqual([]);
  });

  test("home shows headline findings and the data date", async ({ page }) => {
    await page.goto("#/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator(".headline").first()).toBeVisible();
    await expect(page.locator(".footer")).toContainText(/as of \w+ \d{4}/);
  });

  test("tag explorer runs DuckDB queries for a mix", async ({ page }) => {
    await page.goto("#/explore?tags=Roguelike,Deckbuilding");
    const effect = page.locator(".card", { hasText: "Mix effect" });
    await expect(effect).toContainText(/[+−±]\d+\.\d pp/);
    await expect(page.locator(".card", { hasText: "Games" }).first()).toContainText(/\d/);
    await expect(page.locator(".two-col table tbody tr").first()).toBeVisible(); // companions
    await expect(page).toHaveTitle(/Roguelike \+ Deckbuilding/);
  });

  test("hidden gems lists ranked mixes", async ({ page }) => {
    await page.goto("#/gems");
    await expect(page.locator(".gem").first()).toBeVisible();
    expect(await page.locator(".gem").count()).toBeGreaterThan(5);
  });

  test("game lookup searches and shows a game", async ({ page }) => {
    await page.goto("#/games");
    await page.getByRole("combobox", { name: "Search games" }).fill("hades");
    await page.getByRole("option").first().click();
    await expect(page).toHaveURL(/#\/games\/\d+/);
    await expect(page.locator(".game-title h2")).toContainText(/Hades/i);
    await expect(page.locator(".steam-button")).toHaveAttribute("href", /store\.steampowered\.com\/app\/\d+$/);
    await expect(page.locator(".bar-list li").first()).toBeVisible(); // tag effects
    await expect(page.getByRole("heading", { name: "Mixes it belongs to" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Tagged most like it" })).toBeVisible();
  });

  test("timelines draw a review history with turning points", async ({ page }) => {
    await page.goto("#/timelines?games=275850");
    await expect(page.locator(".timeline-chart svg").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Turning points" })).toBeVisible();
  });

  test("new releases shows tracked games", async ({ page }) => {
    await page.goto("#/releases");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator(".plot svg").first()).toBeVisible();
  });

  test("findings, write-up and methodology render", async ({ page }) => {
    await page.goto("#/findings");
    await expect(page.locator(".finding").first()).toBeVisible();
    await page.goto("#/writeup");
    await expect(page.locator(".writeup-figure .timeline-chart svg").first()).toBeVisible();
    await page.goto("#/methodology");
    await expect(page.getByRole("heading", { name: "Mix effects" })).toBeVisible();
  });

  test("unknown routes show the 404 page", async ({ page }) => {
    await page.goto("#/no-such-page");
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  });
});
