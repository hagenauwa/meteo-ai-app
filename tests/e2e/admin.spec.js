import { test, expect } from "@playwright/test";

test("admin dashboard carica", async ({ page }) => {
    await page.goto("/admin.html");
    await expect(page.locator("text=Dashboard Admin")).toBeVisible();
    await expect(page.locator("text=Stato Sistema")).toBeVisible();
});
