import { API_ENDPOINTS } from "./config.js";

const CITY_SEARCH_CACHE_LIMIT = 40;
const citySearchCache = new Map();

const OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search";
const GEOCODING_RESULT_MULTIPLIER = 3;
const GEOCODING_MAX_COUNT = 50;

const OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast";
const OPEN_METEO_CURRENT_FIELDS =
    "temperature_2m,relative_humidity_2m,apparent_temperature,cloud_cover," +
    "wind_speed_10m,wind_direction_10m,surface_pressure,precipitation,weather_code,is_day";
const OPEN_METEO_DAILY_FIELDS =
    "temperature_2m_max,temperature_2m_min,weather_code," +
    "precipitation_probability_max,precipitation_sum,wind_speed_10m_max,wind_direction_10m_dominant";
const OPEN_METEO_HOURLY_FIELDS =
    "temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,wind_direction_10m," +
    "precipitation_probability,precipitation,weather_code";
const OPEN_METEO_FORECAST_DAYS = 16;
// Ore di dettaglio orario richieste a Open-Meteo: 7 giorni, così anche i giorni
// successivi a oggi hanno la scansione ora-per-ora (prima erano 24h → la card
// oraria era vuota già da "Domani"). Oltre ~7gg il valore orario non è
// significativo e resta il solo riepilogo giornaliero.
const OPEN_METEO_FORECAST_HOURS = 168;

const WMO_CODES = {
    0: ["Cielo sereno", "01d"],
    1: ["Prevalentemente sereno", "02d"],
    2: ["Parzialmente nuvoloso", "02d"],
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

export async function apiFetch(url, options = {}) {
    const headers = {
        "bypass-tunnel-reminder": "true",
        ...(options.headers || {}),
    };
    return fetch(url, { ...options, headers });
}

function normalizeErrorDetail(detail) {
    // FastAPI 422 restituisce `detail` come array di oggetti {loc,msg,type}.
    if (Array.isArray(detail)) {
        return detail.map((item) => item?.msg || JSON.stringify(item)).join("; ");
    }
    if (detail && typeof detail === "object") {
        return JSON.stringify(detail);
    }
    return detail;
}

async function fetchJson(url, options = {}) {
    const response = await apiFetch(url, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(normalizeErrorDetail(body.detail) || body.message || `HTTP ${response.status}`);
    }
    return body;
}

function normalizeText(value) {
    return String(value || "")
        .trim()
        .toLowerCase();
}

function inferLocalityType(raw) {
    const code = String(raw.feature_code || "").toUpperCase();
    if (code.startsWith("PPL")) return "comune";
    if (code.startsWith("ADM")) return "comune";
    return "comune";
}

function normalizeGeocodingResult(raw) {
    return {
        name: raw.name || "",
        region: raw.admin1 || "",
        province: raw.admin2 || "",
        lat: raw.latitude,
        lon: raw.longitude,
        locality_type: inferLocalityType(raw),
        _population: Number(raw.population || 0),
    };
}

function dedupeGeocodingResults(results) {
    const unique = new Map();
    for (const result of results) {
        const lat = Number(result.lat).toFixed(4);
        const lon = Number(result.lon).toFixed(4);
        const key = `${normalizeText(result.name)}|${normalizeText(result.region)}|${lat}|${lon}`;
        if (!unique.has(key)) {
            unique.set(key, result);
        }
    }
    return [...unique.values()];
}

function rankGeocodingResult(a, b, queryLower) {
    const aName = normalizeText(a.name);
    const bName = normalizeText(b.name);

    const aExact = aName === queryLower ? 0 : 1;
    const bExact = bName === queryLower ? 0 : 1;
    if (aExact !== bExact) return aExact - bExact;

    const aPrefix = aName.startsWith(queryLower) ? 0 : 1;
    const bPrefix = bName.startsWith(queryLower) ? 0 : 1;
    if (aPrefix !== bPrefix) return aPrefix - bPrefix;

    if (a._population !== b._population) return b._population - a._population;
    if (aName.length !== bName.length) return aName.length - bName.length;
    return aName.localeCompare(bName, "it");
}

function matchesScope(city, scope) {
    if (scope === "all") return true;
    return city.locality_type === (scope === "localita" ? "localita" : "comune");
}

function formatGeocodingResults(results, query, limit, scope) {
    const queryLower = normalizeText(query);
    const normalized = results
        .filter((item) => item?.country_code === "IT")
        .filter((item) => Number.isFinite(Number(item?.latitude)) && Number.isFinite(Number(item?.longitude)))
        .map(normalizeGeocodingResult)
        .filter((city) => matchesScope(city, scope));

    const deduped = dedupeGeocodingResults(normalized);
    deduped.sort((a, b) => rankGeocodingResult(a, b, queryLower));

    return deduped.slice(0, limit).map(({ _population, ...city }) => city);
}

function formatBackendResults(results, query, limit, scope) {
    // Il backend /api/cities/search restituisce già la forma {name, region,
    // province, lat, lon, locality_type} (NON la forma Open-Meteo), quindi qui
    // non filtriamo per country_code/latitude ma normalizziamo direttamente.
    const queryLower = normalizeText(query);
    const normalized = results
        .filter((item) => Number.isFinite(Number(item?.lat)) && Number.isFinite(Number(item?.lon)))
        .map((item) => ({
            name: item.name || "",
            region: item.region || "",
            province: item.province || "",
            lat: item.lat,
            lon: item.lon,
            locality_type: item.locality_type || "comune",
            _population: Number(item.population || 0),
        }))
        .filter((city) => matchesScope(city, scope));

    const deduped = dedupeGeocodingResults(normalized);
    deduped.sort((a, b) => rankGeocodingResult(a, b, queryLower));

    return deduped.slice(0, limit).map(({ _population, ...city }) => city);
}

async function fetchOpenMeteoGeocoding(query, limit, options = {}) {
    const count = Math.min(GEOCODING_MAX_COUNT, Math.max(limit, limit * GEOCODING_RESULT_MULTIPLIER));

    const params = new URLSearchParams({
        name: query,
        count: String(count),
        language: "it",
        format: "json",
        countryCode: "IT",
    });

    const response = await fetch(`${OPEN_METEO_GEOCODING_URL}?${params.toString()}`, {
        method: "GET",
        signal: options.signal,
    });

    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(body.reason || body.detail || body.message || `Geocoding HTTP ${response.status}`);
    }

    return Array.isArray(body.results) ? body.results : [];
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

async function fetchBackendCitySearch(query, limit, scope, signal) {
    const params = new URLSearchParams({
        q: query,
        limit: String(limit),
        scope,
    });
    const response = await apiFetch(`${API_ENDPOINTS.citySearch}?${params.toString()}`, {
        method: "GET",
        signal,
    });
    if (!response.ok) return [];
    const body = await response.json().catch(() => []);
    // L'endpoint backend restituisce un ARRAY (response_model=List[CityIndexItem]).
    if (Array.isArray(body)) return body;
    return Array.isArray(body.results) ? body.results : [];
}

export async function searchCities(query, limit = 8, scope = "all", options = {}) {
    const trimmedQuery = query.trim();
    if (!trimmedQuery || trimmedQuery.length < 2) return [];

    const cacheKey = getCitySearchCacheKey(trimmedQuery, limit, scope);

    if (citySearchCache.has(cacheKey)) {
        return citySearchCache.get(cacheKey);
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3000);
    let backendRaw = [];
    try {
        backendRaw = await fetchBackendCitySearch(trimmedQuery, limit, scope, controller.signal);
    } catch {
        // Fallback silenzioso a Open-Meteo
    } finally {
        clearTimeout(timeoutId);
    }

    if (backendRaw.length > 0) {
        const results = formatBackendResults(backendRaw, trimmedQuery, limit, scope);
        if (results.length > 0) {
            storeCitySearchResult(cacheKey, results);
            return results;
        }
    }

    const rawResults = await fetchOpenMeteoGeocoding(trimmedQuery, limit, options);
    const results = formatGeocodingResults(rawResults, trimmedQuery, limit, scope);
    storeCitySearchResult(cacheKey, results);
    return results;
}

export function warmCitiesSearch() {
    return searchCities("roma", 1, "comuni").catch(() => []);
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
    if (code >= 51 && code <= 99) return 88;
    return 55;
}

function isRainWmoCode(code) {
    return [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99].includes(Number(code));
}

// Deriva il codice meteo giornaliero dalle ore effettive. Allineato al backend
// notification_utils._derive_daily_weather_code_from_hourly: quando le ore hanno
// pioggia si usa il codice orario più severo REALMENTE presente, invece del
// codice giornaliero aggregato di Open-Meteo che può segnare falsi "Temporali".
function deriveDailyWmoFromHourly(dailyDate, fallbackCode, hourly = {}) {
    const times = hourly.time || [];
    if (!dailyDate || !times.length) return fallbackCode;

    const entries = [];
    for (let i = 0; i < times.length; i++) {
        if (!String(times[i]).startsWith(String(dailyDate))) continue;
        entries.push({
            code: (hourly.weather_code || [])[i],
            cloud: (hourly.cloud_cover || [])[i],
            pop: (hourly.precipitation_probability || [])[i] || 0,
            precipitation: (hourly.precipitation || [])[i] || 0,
        });
    }

    if (!entries.length) return fallbackCode;

    if (entries.some((entry) => isRainWmoCode(entry.code) || entry.precipitation > 0.1)) {
        const rainCodes = entries
            .map((entry) => entry.code)
            .filter((code) => code != null && isRainWmoCode(code))
            .map(Number);
        // Solo pioggia normale nelle ore → codice orario più rappresentativo,
        // evitando i falsi "Temporali" del daily aggregato di Open-Meteo.
        if (rainCodes.length) return Math.max(...rainCodes);
        return fallbackCode;
    }

    if (entries.some((entry) => (entry.pop || 0) >= 40)) return fallbackCode;

    const codesPresent = entries.map((entry) => entry.code).filter((code) => code != null);
    if (codesPresent.includes(45) || codesPresent.includes(48)) return fallbackCode;

    const cloudyFraction = codesPresent.length
        ? codesPresent.filter((code) => code === 3).length / codesPresent.length
        : 0;
    const partlyFraction = codesPresent.length
        ? codesPresent.filter((code) => code === 2).length / codesPresent.length
        : 0;

    const clouds = entries.map((entry) => Number(entry.cloud)).filter((value) => Number.isFinite(value));
    if (clouds.length) {
        const avgCloud = clouds.reduce((sum, value) => sum + value, 0) / clouds.length;
        const maxCloud = Math.max(...clouds);
        if (avgCloud <= 20 && maxCloud <= 35) return 0;
        if (avgCloud <= 35 && cloudyFraction < 0.25) return 1;
        if (avgCloud <= 65 || partlyFraction >= 0.35) return 2;
        return 3;
    }

    if (cloudyFraction >= 0.5) return 3;
    if (partlyFraction >= 0.35) return 2;
    if (codesPresent.length) return codesPresent.includes(1) ? 1 : 0;
    return fallbackCode;
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

    const hourlyTimes = hourly.time || [];
    const now = new Date();
    const currentDatePrefix = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    const currentHourPrefix = `${currentDatePrefix}T${String(now.getHours()).padStart(2, "0")}`;
    const currentHourIndex = hourlyTimes.findIndex((t) => String(t).startsWith(currentHourPrefix));

    const hourlyWmo = currentHourIndex >= 0 ? (hourly.weather_code || [])[currentHourIndex] : null;
    const hourlyPop =
        currentHourIndex >= 0 ? ((hourly.precipitation_probability || [])[currentHourIndex] || 0) / 100 : 0;
    const hourlyPrecip = currentHourIndex >= 0 ? (hourly.precipitation || [])[currentHourIndex] || 0 : 0;

    const currentWmo = current.weather_code || 0;
    const hourHasRain = (hourlyWmo && hourlyWmo >= 51) || hourlyPop >= 0.5 || hourlyPrecip > 0;
    const currentHasRain = (current.precipitation || 0) > 0 || currentWmo >= 51;
    const currentIsNight = Number(current.is_day) === 0;

    const effectiveWmo = hourHasRain && !currentHasRain ? hourlyWmo || 61 : currentWmo;
    const pop = currentHasRain || hourHasRain ? 1 : 0;
    const [description, icon] = wmoToDescription(effectiveWmo, currentIsNight);

    const currentFormatted = {
        temp: Math.round((current.temperature_2m || 0) * 10) / 10,
        feels_like: Math.round((current.apparent_temperature || 0) * 10) / 10,
        humidity: current.relative_humidity_2m || 0,
        pressure: Math.round(current.surface_pressure || 1013),
        wind_speed: Math.round((current.wind_speed_10m || 0) * 10) / 10,
        wind_deg: current.wind_direction_10m || 0,
        // Open-Meteo non fornisce la visibilità nel blocco "current": usa l'ora
        // corrente se disponibile fra gli hourly, altrimenti null (mostrato come "--").
        visibility: currentHourIndex >= 0 ? ((hourly.visibility || [])[currentHourIndex] ?? null) : null,
        clouds: current.cloud_cover || 0,
        precipitation: current.precipitation || 0,
        pop,
        weather_code: effectiveWmo,
        weather: [{ description, icon }],
    };

    const hourlyFormatted = [];
    const hourlyLimit = Math.min(hourlyTimes.length, OPEN_METEO_FORECAST_HOURS);

    for (let i = 0; i < hourlyLimit; i++) {
        const wmoCode = (hourly.weather_code || [])[i] || 0;
        const hour = Number(String(hourlyTimes[i] || "").slice(11, 13));
        const isNight = Number.isFinite(hour) ? hour < 6 || hour >= 18 : false;
        const [hourDesc, hourIcon] = wmoToDescription(wmoCode, isNight);
        hourlyFormatted.push({
            dt: hourlyTimes[i],
            lead_hours: i,
            temp: Math.round(((hourly.temperature_2m || [])[i] || 0) * 10) / 10,
            humidity: (hourly.relative_humidity_2m || [])[i] || 0,
            cloud_cover: (hourly.cloud_cover || [])[i] || 0,
            wind_speed: Math.round(((hourly.wind_speed_10m || [])[i] || 0) * 10) / 10,
            wind_deg: (hourly.wind_direction_10m || [])[i] || 0,
            precipitation: (hourly.precipitation || [])[i] || 0,
            pop: ((hourly.precipitation_probability || [])[i] || 0) / 100,
            weather: [{ description: hourDesc, icon: hourIcon }],
            weather_code: wmoCode,
        });
    }

    const dailyTimes = daily.time || [];
    const dailyFormatted = [];

    for (let i = 0; i < dailyTimes.length; i++) {
        const rawWmoCode = (daily.weather_code || [])[i] || 0;
        const wmoCode = deriveDailyWmoFromHourly(dailyTimes[i], rawWmoCode, hourly);
        const [dayDesc, dayIcon] = wmoToDescription(wmoCode);
        const minTemp = (daily.temperature_2m_min || [])[i] || 0;
        const maxTemp = (daily.temperature_2m_max || [])[i] || 0;

        dailyFormatted.push({
            dt: dailyTimes[i],
            temp: {
                min: Math.round(minTemp * 10) / 10,
                max: Math.round(maxTemp * 10) / 10,
                day: Math.round(((minTemp + maxTemp) / 2) * 10) / 10,
            },
            humidity: 50,
            cloud_cover: approxCloudCoverFromWmo(wmoCode),
            wind_speed: Math.round(((daily.wind_speed_10m_max || [])[i] || 0) * 10) / 10,
            wind_deg: (daily.wind_direction_10m_dominant || [])[i] || 0,
            pop: ((daily.precipitation_probability_max || [])[i] || 0) / 100,
            precipitation_sum: Math.round(((daily.precipitation_sum || [])[i] || 0) * 10) / 10,
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
                wind_speed: weatherPayload.current?.wind_speed,
                wind_deg: weatherPayload.current?.wind_deg,
                precipitation: weatherPayload.current?.precipitation,
                weather_code: weatherPayload.current?.weather_code,
            },
            daily: weatherPayload.daily.map((day) => ({
                dt: day.dt,
                temp: day.temp,
                humidity: day.humidity,
                cloud_cover: day.cloud_cover,
                wind_speed: day.wind_speed,
                wind_deg: day.wind_deg,
                pop: day.pop,
                precipitation_sum: day.precipitation_sum,
                weather_code: day.weather_code,
            })),
        }),
    });
}

export async function fetchWeatherAdvanced(city) {
    let resolvedCity = city;
    if (resolvedCity.lat == null || resolvedCity.lon == null) {
        const candidates = await searchCities(resolvedCity.name || "", 1, "comuni");
        if (!candidates.length) {
            throw new Error("Coordinate mancanti per questa città");
        }
        resolvedCity = { ...resolvedCity, ...candidates[0] };
    }
    const params = new URLSearchParams({
        city: resolvedCity.name,
        lat: String(resolvedCity.lat),
        lon: String(resolvedCity.lon),
    });
    return fetchJson(`${API_ENDPOINTS.weatherAdvanced}?${params.toString()}`);
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
