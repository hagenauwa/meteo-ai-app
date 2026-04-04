import {
    fetchWeatherByCity,
    loadCityIndex,
    searchCities,
} from "./api.js";
import { createAutocomplete } from "./autocomplete.js";
import { hideError, renderChipList, renderWeather, showError, showLoading } from "./render.js";
import { clearRecents, getFavorites, getRecents, pushRecent, removeRecent, toggleFavorite } from "./storage.js";

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
    const recents = getRecents();

    renderChipList("favoritesList", getFavorites(), executeSearch);
    renderChipList("recentList", recents, executeSearch, {
        onRemove: city => {
            removeRecent(city.name);
            renderSavedCities();
        },
    });

    const clearRecentsBtn = document.getElementById("clearRecentsBtn");
    if (clearRecentsBtn) {
        clearRecentsBtn.classList.toggle("hidden", recents.length === 0);
    }
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
        let isRefreshing = false;
        let registrationRef = null;

        const reloadForUpdate = () => {
            if (isRefreshing) return;
            isRefreshing = true;
            window.location.reload();
        };

        const activateWaitingWorker = worker => {
            if (!worker) return;
            worker.postMessage({ type: "SKIP_WAITING" });
        };

        const trackInstallingWorker = worker => {
            if (!worker) return;
            worker.addEventListener("statechange", () => {
                if (worker.state === "installed" && navigator.serviceWorker.controller) {
                    activateWaitingWorker(worker);
                }
            });
        };

        navigator.serviceWorker.addEventListener("controllerchange", reloadForUpdate);

        navigator.serviceWorker
            .register("/service-worker.js", { updateViaCache: "none" })
            .then(registration => {
                registrationRef = registration;
                trackInstallingWorker(registration.installing);
                activateWaitingWorker(registration.waiting);

                registration.addEventListener("updatefound", () => {
                    trackInstallingWorker(registration.installing);
                });

                registration.update().catch(() => {});
            })
            .catch(() => {});

        const checkForUpdates = () => {
            registrationRef?.update().catch(() => {});
        };

        window.addEventListener("focus", checkForUpdates);
        document.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "visible") {
                checkForUpdates();
            }
        });
    }
}

function registerCityInputSelection(input) {
    let selectOnPointerUp = false;

    const selectAll = () => {
        if (!input.value.trim()) return;
        requestAnimationFrame(() => {
            input.setSelectionRange(0, input.value.length);
        });
    };

    input.addEventListener("pointerdown", () => {
        selectOnPointerUp = !!input.value.trim();
    });

    input.addEventListener("focus", selectAll);

    input.addEventListener("pointerup", () => {
        if (!selectOnPointerUp) return;
        selectOnPointerUp = false;
        selectAll();
    });

    input.addEventListener("blur", () => {
        selectOnPointerUp = false;
    });
}

document.addEventListener("DOMContentLoaded", async () => {
    const input = document.getElementById("cityInput");
    const searchBtn = document.getElementById("searchBtn");
    const autocompleteList = document.getElementById("autocompleteList");
    const clearRecentsBtn = document.getElementById("clearRecentsBtn");

    renderSavedCities();
    registerFavoriteButton();
    registerPwa();
    registerCityInputSelection(input);

    searchBtn.addEventListener("click", searchFromInput);
    input.addEventListener("keypress", event => {
        if (event.key === "Enter") searchFromInput();
    });

    clearRecentsBtn?.addEventListener("click", () => {
        clearRecents();
        renderSavedCities();
    });

    createAutocomplete({
        input,
        list: autocompleteList,
        getLocalMatches: localCityMatches,
        onSelect: executeSearch,
    });
});
