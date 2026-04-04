import { ADMIN_API_TOKEN, API_ENDPOINTS, CITY_INDEX_CACHE_KEY } from "./config.js";

let cityIndexPromise = null;

export async function apiFetch(url, options = {}) {
    const headers = {
        "bypass-tunnel-reminder": "true",
        ...(options.headers || {}),
    };
    return fetch(url, { ...options, headers });
}

async function fetchJson(url, options = {}) {
    const response = await apiFetch(url, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(body.detail || body.message || `HTTP ${response.status}`);
    }
    return body;
}

export function hasAdminToken() {
    return Boolean(ADMIN_API_TOKEN);
}

export async function loadCityIndex() {
    if (cityIndexPromise) return cityIndexPromise;

    cityIndexPromise = (async () => {
        try {
            const cached = localStorage.getItem(CITY_INDEX_CACHE_KEY);
            if (cached) {
                return JSON.parse(cached);
            }
        } catch {
            // ignore cache parse failure
        }

        const url = `${API_ENDPOINTS.cityIndex}?scope=all&version=v2`;
        const data = await fetchJson(url);
        try {
            localStorage.setItem(CITY_INDEX_CACHE_KEY, JSON.stringify(data));
        } catch {
            // ignore storage full
        }
        return data;
    })();

    return cityIndexPromise;
}

export async function searchCities(query, limit = 8, scope = "all") {
    const url = `${API_ENDPOINTS.cities}?q=${encodeURIComponent(query)}&limit=${limit}&scope=${scope}`;
    return fetchJson(url);
}

export async function fetchWeatherByCity(city) {
    const params = new URLSearchParams({ include_ml: "true" });
    if (city.lat != null && city.lon != null) {
        params.set("lat", city.lat);
        params.set("lon", city.lon);
        params.set("name", city.name);
    } else {
        params.set("city", city.name);
    }
    return fetchJson(`${API_ENDPOINTS.weather}?${params.toString()}`);
}

export async function sendChat(payload) {
    return fetchJson(API_ENDPOINTS.chat, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
}

export async function triggerTraining() {
    return fetchJson(API_ENDPOINTS.train, {
        method: "POST",
        headers: { "x-admin-token": ADMIN_API_TOKEN },
    });
}

export async function triggerRunCycle() {
    return fetchJson(API_ENDPOINTS.runCycle, {
        method: "POST",
        headers: { "x-admin-token": ADMIN_API_TOKEN },
    });
}
