import { expect, test } from "@playwright/test";

function isoDate(offsetDays = 0) {
    const date = new Date();
    date.setDate(date.getDate() + offsetDays);
    return date.toISOString().slice(0, 10);
}

async function mockWeatherApis(page, cityName) {
    const today = isoDate();
    const tomorrow = isoDate(1);
    const currentHour = `${today}T${String(new Date().getHours()).padStart(2, "0")}:00`;

    await page.route("https://geocoding-api.open-meteo.com/**", route =>
        route.fulfill({
            json: {
                results: [
                    {
                        id: 1,
                        name: cityName,
                        latitude: 41.9,
                        longitude: 12.5,
                        admin1: "Lazio",
                        admin2: "Roma",
                        country_code: "IT",
                    },
                ],
            },
        })
    );
    await page.route("https://api.open-meteo.com/**", route =>
        route.fulfill({
            json: {
                latitude: 41.9,
                longitude: 12.5,
                current: {
                    time: currentHour,
                    interval: 900,
                    temperature_2m: 24.2,
                    relative_humidity_2m: 58,
                    apparent_temperature: 24.5,
                    cloud_cover: 20,
                    wind_speed_10m: 8,
                    wind_direction_10m: 180,
                    surface_pressure: 1014,
                    precipitation: 0,
                    weather_code: 1,
                    is_day: 1,
                },
                hourly: {
                    time: [currentHour, `${tomorrow}T14:00`],
                    temperature_2m: [24.2, 25],
                    relative_humidity_2m: [58, 55],
                    cloud_cover: [20, 25],
                    wind_speed_10m: [8, 9],
                    wind_direction_10m: [180, 190],
                    precipitation_probability: [5, 10],
                    precipitation: [0, 0],
                    weather_code: [1, 1],
                    visibility: [10000, 10000],
                    surface_pressure: [1014, 1013],
                    dew_point_2m: [15, 15],
                    cape: [0, 0],
                },
                daily: {
                    time: [today, tomorrow],
                    temperature_2m_max: [27, 28],
                    temperature_2m_min: [18, 19],
                    weather_code: [1, 1],
                    precipitation_probability_max: [5, 10],
                    precipitation_sum: [0, 0],
                    wind_speed_10m_max: [10, 11],
                    wind_direction_10m_dominant: [180, 190],
                },
            },
        })
    );
    await page.route("https://meteo-ai-backend.onrender.com/**", route => {
        const url = new URL(route.request().url());
        if (url.pathname === "/api/cities/search") {
            return route.fulfill({
                json: [
                    {
                        name: cityName,
                        lat: 41.9,
                        lon: 12.5,
                        region: "Lazio",
                        province: "Roma",
                        locality_type: "comune",
                    },
                ],
            });
        }
        if (url.pathname === "/api/ml/enrich") {
            return route.fulfill({ json: { ml: { enabled: false }, daily_ml: [] } });
        }
        return route.fulfill({ status: 503, json: { detail: "optional test dependency" } });
    });
}

test("ricerca città e visualizzazione meteo", async ({ page }) => {
    await mockWeatherApis(page, "Roma");
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
    await mockWeatherApis(page, "Milano");
    await page.goto("/");
    await page.locator("#cityInput").fill("Milano");
    await page.locator("#cityInput").press("Enter");
    await page.waitForSelector("#cityName", { timeout: 15000 });
    const btn = page.locator("#favoriteBtn");
    await btn.click();
    await expect(page.locator("#favoritesList")).toContainText("Milano");
});
