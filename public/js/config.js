export const BACKEND_URL = window.BACKEND_URL || "http://localhost:8000";
export const ADMIN_API_TOKEN = window.ADMIN_API_TOKEN || "";
export const CITY_INDEX_CACHE_KEY = "meteo_city_index_v2_all";
export const LAST_CITY_KEY = "meteo_last_city";
export const FAVORITES_KEY = "meteo_favorites_v1";
export const RECENTS_KEY = "meteo_recent_v1";

export const API_ENDPOINTS = {
    weather: `${BACKEND_URL}/api/weather`,
    cities: `${BACKEND_URL}/api/cities`,
    cityIndex: `${BACKEND_URL}/api/cities/index`,
    mlStats: `${BACKEND_URL}/api/ml/stats`,
    train: `${BACKEND_URL}/api/ml/train`,
    runCycle: `${BACKEND_URL}/api/admin/run-cycle`,
    chat: `${BACKEND_URL}/api/chat`,
};

export const WEATHER_ICONS = {
    "01d": "fa-sun",
    "01n": "fa-moon",
    "02d": "fa-cloud-sun",
    "02n": "fa-cloud-moon",
    "03d": "fa-cloud",
    "03n": "fa-cloud",
    "04d": "fa-cloud",
    "04n": "fa-cloud",
    "09d": "fa-cloud-showers-heavy",
    "09n": "fa-cloud-showers-heavy",
    "10d": "fa-cloud-rain",
    "10n": "fa-cloud-rain",
    "11d": "fa-bolt",
    "11n": "fa-bolt",
    "13d": "fa-snowflake",
    "13n": "fa-snowflake",
    "50d": "fa-smog",
    "50n": "fa-smog",
};
