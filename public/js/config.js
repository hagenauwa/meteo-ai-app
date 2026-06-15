export const BACKEND_URL = window.BACKEND_URL || "http://localhost:8000";
export const FAVORITES_KEY = "meteo_favorites_v1";
export const RECENTS_KEY = "meteo_recent_v1";
export const SUPPORTER_TOKEN_KEY = "le_previsioni_supporter_token_v1";

export const API_ENDPOINTS = {
    mlEnrich: `${BACKEND_URL}/api/ml/enrich`,
    supporterCheckout: `${BACKEND_URL}/api/supporters/checkout-session`,
    supporterConfirm: `${BACKEND_URL}/api/supporters/confirm-session`,
    supporterStatus: `${BACKEND_URL}/api/supporters/status`,
    citySearch: `${BACKEND_URL}/api/cities/search`,
    weatherAdvanced: `${BACKEND_URL}/api/weather/advanced`,
    telegramLinkCode: `${BACKEND_URL}/api/telegram/link-code`,
    telegramStatus: `${BACKEND_URL}/api/telegram/status`,
    telegramPreferences: `${BACKEND_URL}/api/telegram/preferences`,
    telegramUnlink: `${BACKEND_URL}/api/telegram/unlink`,
};

export const WEATHER_ICON_ASSETS = {
    "01d": "/icons/weather/clear-day.svg",
    "01n": "/icons/weather/clear-night.svg",
    "02d": "/icons/weather/partly-cloudy-day.svg",
    "02n": "/icons/weather/partly-cloudy-night.svg",
    "03d": "/icons/weather/cloudy.svg",
    "03n": "/icons/weather/cloudy.svg",
    "04d": "/icons/weather/overcast.svg",
    "04n": "/icons/weather/overcast.svg",
    "09d": "/icons/weather/drizzle.svg",
    "09n": "/icons/weather/drizzle.svg",
    "10d": "/icons/weather/rain.svg",
    "10n": "/icons/weather/rain.svg",
    "11d": "/icons/weather/thunderstorm.svg",
    "11n": "/icons/weather/thunderstorm.svg",
    "13d": "/icons/weather/snow.svg",
    "13n": "/icons/weather/snow.svg",
    "50d": "/icons/weather/fog.svg",
    "50n": "/icons/weather/fog.svg",
    unknown: "/icons/weather/unknown.svg",
};
