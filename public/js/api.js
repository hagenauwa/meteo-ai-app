import { API_ENDPOINTS } from "./config.js";

const CITY_SEARCH_CACHE_LIMIT = 40;
const citySearchCache = new Map();

const CITIES_INDEX_SCOPE = "comuni";
const CITIES_INDEX_VERSION = "v2";
const CITIES_INDEX_STORAGE_KEY = `meteo_cities_index_${CITIES_INDEX_SCOPE}_${CITIES_INDEX_VERSION}`;
const CITIES_INDEX_STORAGE_TS_KEY = `${CITIES_INDEX_STORAGE_KEY}_ts`;
const CITIES_INDEX_TTL_MS = 30 * 24 * 60 * 60 * 1000;

const OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast";
const OPEN_METEO_CURRENT_FIELDS = (
    "temperature_2m,relative_humidity_2m,apparent_temperature,cloud_cover," +
    "wind_speed_10m,wind_direction_10m,surface_pressure,precipitation,weather_code"
);
const OPEN_METEO_DAILY_FIELDS = (
    "temperature_2m_max,temperature_2m_min,weather_code," +
    "precipitation_probability_max,wind_speed_10m_max,wind_direction_10m_dominant"
);
const OPEN_METEO_HOURLY_FIELDS = (
    "temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,wind_direction_10m," +
    "precipitation_probability,precipitation,weather_code"
);
const OPEN_METEO_FORECAST_DAYS = 16;
const OPEN_METEO_FORECAST_HOURS = 24;

const WMO_CODES = {
    0: ["Cielo sereno", "01d"],
    1: ["Prevalentemente sereno", "02d"],
    2: ["Parzialmente nuvoloso", "03d"],
    3: ["Nuvoloso", "04d"],
    45: ["Nebbia", "50d"],
    48: ["Nebbia con brina", "50d"],
    51: ["Pioggerella leggera", "09d"],
    53: ["Pioggerella moderata", "09d"],
    55: ["Pioggerella intensa", "09d"],
    61: ["Pioggia leggera", "10d"],
    63: ["Pioggia moderata", "10d"],
    65: ["Pioggia intensa", "10d"],
    71: ["Neve leggera", "13d"],
    73: ["Neve moderata", "13d"],
    75: ["Neve intensa", "13d"],
    80: ["Rovesci leggeri", "09d"],
    81: ["Rovesci moderati", "09d"],
    82: ["Rovesci violenti", "09d"],
    95: ["Temporale", "11d"],
    96: ["Temporale con grandine", "11d"],
    99: ["Temporale con grandine intensa", "11d"],
};

let citiesIndexPromise = null;

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

function readLocalJson(key, fallback = null) {
    try {
        const raw = localStorage.getItem(key);
        if (!raw) return fallback;
        return JSON.parse(raw);
    } catch {
        return fallback;
    }
}

function readLocalValue(key, fallback = "") {
    try {
        const value = localStorage.getItem(key);
        return value == null ? fallback : value;
    } catch {
        return fallback;
    }
}

function writeLocalJson(key, value) {
    try {
        localStorage.setItem(key, JSON.stringify(value));
    } catch {
        // ignore storage quota or private mode errors
    }
}

function writeLocalValue(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch {
        // ignore storage quota or private mode errors
    }
}

function normalizeCityRow(city) {
    return {
        name: city.name,
        region: city.region || "",
        province: city.province || "",
        lat: city.lat,
        lon: city.lon,
        locality_type: city.locality_type || "comune",
        name_lower: (city.name || "").toLowerCase(),
    };
}

function rankCities(a, b) {
    const aType = a.locality_type === "comune" ? 0 : 1;
    const bType = b.locality_type === "comune" ? 0 : 1;
    if (aType !== bType) return aType - bType;
    if (a.name.length !== b.name.length) return a.name.length - b.name.length;
    return a.name_lower.localeCompare(b.name_lower, "it");
}

function matchesScope(city, scope) {
    if (scope === "all") return true;
    return city.locality_type === (scope === "localita" ? "localita" : "comune");
}

function searchCitiesInIndex(index, query, limit, scope) {
    const q = query.trim().toLowerCase();
    const startsWith = [];
    const contains = [];

    for (const city of index) {
        if (!matchesScope(city, scope)) continue;
        if (city.name_lower.startsWith(q)) {
            startsWith.push(city);
        } else if (city.name_lower.includes(q)) {
            contains.push(city);
        }
    }

    startsWith.sort(rankCities);
    contains.sort(rankCities);
    return [...startsWith, ...contains].slice(0, limit).map(city => ({
        name: city.name,
        region: city.region,
        province: city.province,
        lat: city.lat,
        lon: city.lon,
        locality_type: city.locality_type,
    }));
}

async function loadCitiesIndex(options = {}) {
    if (citiesIndexPromise) {
        return citiesIndexPromise;
    }

    const now = Date.now();
    const storedAt = Number(readLocalValue(CITIES_INDEX_STORAGE_TS_KEY, "0") || 0);
    const cached = readLocalJson(CITIES_INDEX_STORAGE_KEY, null);
    if (Array.isArray(cached) && cached.length && (now - storedAt) < CITIES_INDEX_TTL_MS) {
        citiesIndexPromise = Promise.resolve(cached.map(normalizeCityRow));
        return citiesIndexPromise;
    }

    const url = `${API_ENDPOINTS.citiesIndex}?scope=${CITIES_INDEX_SCOPE}&version=${CITIES_INDEX_VERSION}`;
    citiesIndexPromise = fetchJson(url, options)
        .then(data => {
            if (!Array.isArray(data)) {
                throw new Error("Indice città non valido");
            }
            const normalized = data.map(normalizeCityRow);
            writeLocalJson(CITIES_INDEX_STORAGE_KEY, normalized);
            writeLocalValue(CITIES_INDEX_STORAGE_TS_KEY, String(Date.now()));
            return normalized;
        })
        .catch(error => {
            citiesIndexPromise = null;
            throw error;
        });

    return citiesIndexPromise;
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
    if (!trimmedQuery) return [];

    const cacheKey = getCitySearchCacheKey(trimmedQuery, limit, scope);

    if (citySearchCache.has(cacheKey)) {
        return citySearchCache.get(cacheKey);
    }

    const cityIndex = await loadCitiesIndex(options);
    const results = searchCitiesInIndex(cityIndex, trimmedQuery, limit, scope);
    storeCitySearchResult(cacheKey, results);
    return results;
}

export function warmCitiesSearch() {
    return searchCities("ro", 1, "comuni").catch(() => []);
}

function wmoToDescription(code, isNight = false) {
    const [description, icon] = WMO_CODES[code] || ["Condizioni variabili", "02d"];
    if (isNight && icon.endsWith("d")) {
        return [description, `${icon.slice(0, -1)}n`];
    }
    return [description, icon];
}

function approxCloudCoverFromWmo(code) {
    if (code === 0 || code === 1) return 12;
    if (code === 2) return 45;
    if (code === 3 || code === 45 || code === 48) return 82;
    return 88;
}

function buildOpenMeteoUrl(lat, lon) {
    const params = new URLSearchParams({
        latitude: String(lat),
        longitude: String(lon),
        current: OPEN_METEO_CURRENT_FIELDS,
        hourly: OPEN_METEO_HOURLY_FIELDS,
        daily: OPEN_METEO_DAILY_FIELDS,
        wind_speed_unit: "kmh",
        timezone: "Europe/Rome",
        forecast_days: String(OPEN_METEO_FORECAST_DAYS),
        forecast_hours: String(OPEN_METEO_FORECAST_HOURS),
    });
    return `${OPEN_METEO_URL}?${params.toString()}`;
}

async function fetchOpenMeteoRaw(lat, lon, options = {}) {
    const response = await fetch(buildOpenMeteoUrl(lat, lon), {
        method: "GET",
        signal: options.signal,
    });

    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(body.reason || body.detail || body.message || `Open-Meteo HTTP ${response.status}`);
    }
    if (!body.current || !body.hourly || !body.daily) {
        throw new Error("Risposta Open-Meteo incompleta");
    }
    return body;
}

function formatWeatherForFrontend(rawData, cityName) {
    const current = rawData.current || {};
    const hourly = rawData.hourly || {};
    const daily = rawData.daily || {};

    const [description, icon] = wmoToDescription(current.weather_code || 0);
    const currentFormatted = {
        temp: Math.round((current.temperature_2m || 0) * 10) / 10,
        feels_like: Math.round((current.apparent_temperature || 0) * 10) / 10,
        humidity: current.relative_humidity_2m || 0,
        pressure: Math.round(current.surface_pressure || 1013),
        wind_speed: Math.round((current.wind_speed_10m || 0) * 10) / 10,
        wind_deg: current.wind_direction_10m || 0,
        visibility: 10000,
        clouds: current.cloud_cover || 0,
        precipitation: current.precipitation || 0,
        weather: [{ description, icon }],
    };

    const hourlyTimes = hourly.time || [];
    const hourlyFormatted = [];
    const hourlyLimit = Math.min(hourlyTimes.length, OPEN_METEO_FORECAST_HOURS);

    for (let i = 0; i < hourlyLimit; i++) {
        const wmoCode = (hourly.weather_code || [])[i] || 0;
        const [hourDesc, hourIcon] = wmoToDescription(wmoCode);
        hourlyFormatted.push({
            dt: hourlyTimes[i],
            lead_hours: i,
            temp: Math.round((((hourly.temperature_2m || [])[i] || 0) * 10)) / 10,
            humidity: (hourly.relative_humidity_2m || [])[i] || 0,
            cloud_cover: (hourly.cloud_cover || [])[i] || 0,
            wind_speed: Math.round((((hourly.wind_speed_10m || [])[i] || 0) * 10)) / 10,
            wind_deg: (hourly.wind_direction_10m || [])[i] || 0,
            precipitation: (hourly.precipitation || [])[i] || 0,
            pop: (((hourly.precipitation_probability || [])[i] || 0) / 100),
            weather: [{ description: hourDesc, icon: hourIcon }],
            weather_code: wmoCode,
        });
    }

    const dailyTimes = daily.time || [];
    const dailyFormatted = [];

    for (let i = 0; i < dailyTimes.length; i++) {
        const wmoCode = (daily.weather_code || [])[i] || 0;
        const [dayDesc, dayIcon] = wmoToDescription(wmoCode);
        const minTemp = ((daily.temperature_2m_min || [])[i] || 0);
        const maxTemp = ((daily.temperature_2m_max || [])[i] || 0);

        dailyFormatted.push({
            dt: dailyTimes[i],
            temp: {
                min: Math.round(minTemp * 10) / 10,
                max: Math.round(maxTemp * 10) / 10,
                day: Math.round((((minTemp + maxTemp) / 2) * 10)) / 10,
            },
            humidity: 50,
            cloud_cover: approxCloudCoverFromWmo(wmoCode),
            wind_speed: Math.round((((daily.wind_speed_10m_max || [])[i] || 0) * 10)) / 10,
            wind_deg: (daily.wind_direction_10m_dominant || [])[i] || 0,
            pop: (((daily.precipitation_probability_max || [])[i] || 0) / 100),
            weather: [{ description: dayDesc, icon: dayIcon }],
            weather_code: wmoCode,
        });
    }

    return {
        current: currentFormatted,
        hourly: hourlyFormatted,
        daily: dailyFormatted,
        lat: rawData.latitude,
        lon: rawData.longitude,
        name: cityName,
        timezone: "Europe/Rome",
    };
}

export async function fetchWeatherByCity(city) {
    let resolvedCity = city;
    if (resolvedCity.lat == null || resolvedCity.lon == null) {
        const candidates = await searchCities(resolvedCity.name || "", 1, "comuni");
        if (!candidates.length) {
            throw new Error("Coordinate mancanti per questa città");
        }
        resolvedCity = {
            ...resolvedCity,
            ...candidates[0],
        };
    }

    const raw = await fetchOpenMeteoRaw(resolvedCity.lat, resolvedCity.lon);
    const formatted = formatWeatherForFrontend(raw, resolvedCity.name);
    formatted.city = {
        name: resolvedCity.name,
        region: resolvedCity.region || "",
        province: resolvedCity.province || "",
        locality_type: resolvedCity.locality_type || "comune",
    };
    return formatted;
}

export async function fetchMlEnrichment(city, weatherPayload) {
    if (!city || city.lat == null || city.lon == null || !weatherPayload?.daily?.length) {
        return null;
    }

    return fetchJson(API_ENDPOINTS.mlEnrich, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            city: {
                name: city.name,
                lat: city.lat,
                lon: city.lon,
                region: city.region || "",
                province: city.province || "",
            },
            current: {
                temp: weatherPayload.current?.temp,
                humidity: weatherPayload.current?.humidity,
                clouds: weatherPayload.current?.clouds,
            },
            daily: weatherPayload.daily.map(day => ({
                dt: day.dt,
                temp: day.temp,
                humidity: day.humidity,
                cloud_cover: day.cloud_cover,
                wind_speed: day.wind_speed,
                wind_deg: day.wind_deg,
                pop: day.pop,
                weather_code: day.weather_code,
            })),
        }),
    });
}

export async function createSupporterCheckoutSession(email) {
    return fetchJson(API_ENDPOINTS.supporterCheckout, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ email }),
    });
}

export async function confirmSupporterSession(sessionId) {
    return fetchJson(API_ENDPOINTS.supporterConfirm, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ session_id: sessionId }),
    });
}

export async function getSupporterStatus(token) {
    return fetchJson(API_ENDPOINTS.supporterStatus, {
        headers: {
            "x-supporter-token": token,
        },
    });
}
