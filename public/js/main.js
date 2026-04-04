import {
    fetchWeatherByCity,
    loadCityIndex,
    searchCities,
} from "./api.js";
import { createAutocomplete } from "./autocomplete.js";
import { hideError, renderChipList, renderWeather, showError, showLoading } from "./render.js";
import { getFavorites, getLastCity, getRecents, pushRecent, toggleFavorite } from "./storage.js";

let currentCity = null;
let currentPayload = null;
let selectedDayIndex = 0;

function normalize(value) {
    return value
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "");
}

function isFavoriteCity(city) {
    if (!city) return false;
    return getFavorites().some(item => item.name.toLowerCase() === city.name.toLowerCase());
}

function updateFavoriteButtonState() {
    const button = document.getElementById("favoriteBtn");
    if (!button) return;

    const active = isFavoriteCity(currentCity);
    button.innerHTML = active
        ? '<i class="fas fa-star"></i><span>Salvata tra preferite</span>'
        : '<i class="far fa-star"></i><span>Salva tra preferite</span>';
    button.classList.toggle("is-active", active);
}

function renderCurrentView() {
    if (!currentPayload) return;

    renderWeather(currentPayload, {
        selectedDayIndex,
        onDaySelect: nextIndex => {
            selectedDayIndex = nextIndex;
            renderCurrentView();
        },
    });
    updateFavoriteButtonState();
}

async function localCityMatches(query) {
    const q = normalize(query);
    const cities = await loadCityIndex();
    const starts = cities
        .filter(city => normalize(city.name).startsWith(q))
        .slice(0, 8);

    if (starts.length >= 8) return starts;

    const found = new Set(starts.map(city => normalize(city.name)));
    const contains = cities
        .filter(city => !found.has(normalize(city.name)) && normalize(city.name).includes(q))
        .slice(0, 8 - starts.length);
    return [...starts, ...contains];
}

async function executeSearch(city) {
    hideError();
    showLoading(true);

    try {
        const payload = await fetchWeatherByCity(city);
        currentPayload = payload;
        currentCity = {
            name: payload.city?.name || payload.name,
            lat: payload.lat,
            lon: payload.lon,
            region: payload.city?.region || city.region || "",
            province: payload.city?.province || city.province || "",
        };

        selectedDayIndex = payload.daily?.length > 1 ? 1 : 0;
        pushRecent(currentCity);
        renderSavedCities();
        renderCurrentView();
    } catch (error) {
        showError(error.message || "Errore durante la ricerca meteo");
    }
}

async function searchFromInput() {
    const input = document.getElementById("cityInput");
    const value = input.value.trim();
    if (!value) {
        showError("Inserisci il nome di una citta.");
        return;
    }

    try {
        const results = await searchCities(value, 1, "all");
        if (!results.length) {
            throw new Error(`Citta "${value}" non trovata`);
        }
        await executeSearch(results[0]);
    } catch (error) {
        showError(error.message);
    }
}

function renderSavedCities() {
    renderChipList("favoritesList", getFavorites(), executeSearch);
    renderChipList("recentList", getRecents(), executeSearch);
}

function registerFavoriteButton() {
    const button = document.getElementById("favoriteBtn");
    if (!button) return;

    button.addEventListener("click", () => {
        if (!currentCity) {
            showError("Cerca prima una citta da salvare.");
            return;
        }

        const added = toggleFavorite(currentCity);
        renderSavedCities();
        updateFavoriteButtonState();

        if (added) {
            hideError();
        }
    });
}

function registerPwa() {
    if ("serviceWorker" in navigator) {
        navigator.serviceWorker.register("/service-worker.js").catch(() => {});
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    const input = document.getElementById("cityInput");
    const searchBtn = document.getElementById("searchBtn");
    const autocompleteList = document.getElementById("autocompleteList");

    renderSavedCities();
    registerFavoriteButton();
    registerPwa();

    searchBtn.addEventListener("click", searchFromInput);
    input.addEventListener("keypress", event => {
        if (event.key === "Enter") searchFromInput();
    });

    document.querySelectorAll(".city-chip[data-city]").forEach(chip => {
        chip.addEventListener("click", async () => {
            input.value = chip.dataset.city;
            await searchFromInput();
        });
    });

    createAutocomplete({
        input,
        list: autocompleteList,
        getLocalMatches: localCityMatches,
        onSelect: executeSearch,
    });

    const lastCity = getLastCity();
    if (lastCity) {
        input.value = lastCity;
        await searchFromInput();
    }
});
