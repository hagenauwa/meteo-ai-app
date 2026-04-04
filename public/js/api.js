import { API_ENDPOINTS } from "./config.js";

const CITY_SEARCH_CACHE_LIMIT = 40;
const citySearchCache = new Map();

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

function getCitySearchCacheKey(query, limit, scope) {
    return `${scope}:${limit}:${query.trim().toLowerCase()}`;
}

function storeCitySearchResult(key, data) {
    if (citySearchCache.has(key)) {
        citySearchCache.delete(key);
    }

    citySearchCache.set(key, data);
    if (citySearchCache.size <= CITY_SEARCH_CACHE_LIMIT) return;

    const oldestKey = citySearchCache.keys().next().value;
    if (oldestKey) {
        citySearchCache.delete(oldestKey);
    }
}

export async function searchCities(query, limit = 8, scope = "all", options = {}) {
    const trimmedQuery = query.trim();
    const cacheKey = getCitySearchCacheKey(trimmedQuery, limit, scope);

    if (citySearchCache.has(cacheKey)) {
        return citySearchCache.get(cacheKey);
    }

    const url = `${API_ENDPOINTS.cities}?q=${encodeURIComponent(trimmedQuery)}&limit=${limit}&scope=${scope}`;
    const data = await fetchJson(url, options);
    storeCitySearchResult(cacheKey, data);
    return data;
}

export function warmCitiesSearch() {
    return searchCities("r", 1, "all").catch(() => []);
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
