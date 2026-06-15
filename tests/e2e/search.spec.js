import { expect, test } from "@playwright/test";

test("ricerca città e visualizzazione meteo", async ({ page }) => {
    await page.goto("/");
    const input = page.locator("#cityInput");
    await input.fill("Roma");
    await input.press("Enter");
    await expect(page.locator("#cityName")).toContainText("Roma", { timeout: 15000 });
    await expect(page.locator("#currentTemp")).not.toHaveText("--");
    await expect(page.locator("#uvIndex")).toBeVisible();
    await expect(page.locator("#airQuality")).toBeVisible();
});

test("toggle preferiti", async ({ page }) => {
    await page.goto("/");
    await page.locator("#cityInput").fill("Milano");
    await page.locator("#cityInput").press("Enter");
    await page.waitForSelector("#cityName", { timeout: 15000 });
    const btn = page.locator("#favoriteBtn");
    await btn.click();
    await expect(page.locator("#favoritesList")).toContainText("Milano");
});
