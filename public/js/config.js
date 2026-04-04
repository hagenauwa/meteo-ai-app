export const BACKEND_URL = window.BACKEND_URL || "http://localhost:8000";
export const FAVORITES_KEY = "meteo_favorites_v1";
export const RECENTS_KEY = "meteo_recent_v1";
export const SUPPORTER_TOKEN_KEY = "le_previsioni_supporter_token_v1";

export const API_ENDPOINTS = {
    weather: `${BACKEND_URL}/api/weather`,
    cities: `${BACKEND_URL}/api/cities`,
    supporterCheckout: `${BACKEND_URL}/api/supporters/checkout-session`,
    supporterConfirm: `${BACKEND_URL}/api/supporters/confirm-session`,
    supporterStatus: `${BACKEND_URL}/api/supporters/status`,
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
