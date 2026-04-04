import { FAVORITES_KEY, LAST_CITY_KEY, RECENTS_KEY } from "./config.js";

function readJson(key, fallback) {
    try {
        return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback));
    } catch {
        return fallback;
    }
}

function writeJson(key, value) {
    localStorage.setItem(key, JSON.stringify(value));
}

export function getFavorites() {
    return readJson(FAVORITES_KEY, []);
}

export function toggleFavorite(city) {
    const favorites = getFavorites();
    const exists = favorites.some(item => item.name.toLowerCase() === city.name.toLowerCase());
    const next = exists
        ? favorites.filter(item => item.name.toLowerCase() !== city.name.toLowerCase())
        : [city, ...favorites].slice(0, 8);
    writeJson(FAVORITES_KEY, next);
    return !exists;
}

export function getRecents() {
    return readJson(RECENTS_KEY, []);
}

export function pushRecent(city) {
    const next = [
        city,
        ...getRecents().filter(item => item.name.toLowerCase() !== city.name.toLowerCase()),
    ].slice(0, 8);
    writeJson(RECENTS_KEY, next);
    localStorage.setItem(LAST_CITY_KEY, city.name);
}

export function getLastCity() {
    return localStorage.getItem(LAST_CITY_KEY) || "";
}
