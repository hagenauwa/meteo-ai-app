import { expect, test } from "@playwright/test";

test("admin dashboard carica", async ({ page }) => {
    await page.route("https://meteo-ai-backend.onrender.com/ready", route =>
        route.fulfill({ json: { status: "ready" } })
    );
    await page.goto("/admin.html");
    await expect(page.locator("text=Dashboard Admin")).toBeVisible();
    await expect(page.locator("text=Stato Sistema")).toBeVisible();
});
