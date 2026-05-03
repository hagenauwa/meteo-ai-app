import {
    fetchWeatherByCity,
    fetchMlEnrichment,
    fetchWeatherAdvanced,
    searchCities,
    warmCitiesSearch,
} from "./api.js";
import { createAutocomplete } from "./autocomplete.js";
import { hideError, renderChipList, renderWeather, showError, showLoading } from "./render.js";
import { initializePush } from "./push.js";
import { initializeSupporterWidget } from "./supporter.js";
import { clearRecents, getFavorites, getRecents, pushRecent, removeRecent, toggleFavorite } from "./storage.js";

let currentCity = null;
let currentPayload = null;
let selectedDayIndex = 0;
let latestSearchToken = 0;
const isLocalDevelopment = ["localhost", "127.0.0.1"].includes(window.location.hostname);

function applyMlEnrichment(payload, enrichment) {
    if (!payload || !enrichment) return payload;

    const merged = {
        ...payload,
        ml: enrichment.ml || payload.ml,
    };

    if (Array.isArray(payload.daily) && Array.isArray(enrichment.daily_ml)) {
        merged.daily = payload.daily.map((day, index) => {
            const dayMl = enrichment.daily_ml[index];
            if (!dayMl) return day;
            return {
                ...day,
                ml: dayMl,
            };
        });
    }

    return merged;
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

async function executeSearch(city) {
    const searchToken = ++latestSearchToken;
    hideError();
    showLoading(true);

    try {
        const payload = await fetchWeatherByCity(city);
        if (searchToken !== latestSearchToken) return;

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

        fetchMlEnrichment(currentCity, payload)
            .then(enrichment => {
                if (!enrichment) return;
                if (searchToken !== latestSearchToken) return;
                currentPayload = applyMlEnrichment(currentPayload, enrichment);
                renderCurrentView();
            })
            .catch(() => {
                // Meteo già mostrato: il blocco ML è un arricchimento opzionale.
            });

        fetchWeatherAdvanced(currentCity)
            .then(advancedPayload => {
                if (!advancedPayload) return;
                if (searchToken !== latestSearchToken) return;
                currentPayload = { ...currentPayload, advanced: advancedPayload.advanced };
                renderCurrentView();
            })
            .catch(() => {
                // Dati avanzati opzionali
            });
    } catch (error) {
        if (searchToken !== latestSearchToken) return;
        showError(error.message || "Errore durante la ricerca meteo");
    }
}

async function searchFromInput() {
    const input = document.getElementById("cityInput");
    const value = input.value.trim();
    if (!value) {
        showError("Inserisci il nome di una città.");
        return;
    }

    try {
        const results = await searchCities(value, 1, "comuni");
        if (!results.length) {
            throw new Error(`Città "${value}" non trovata`);
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
            showError("Cerca prima una città da salvare.");
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

function registerMapButton() {
    const mapBtn = document.getElementById("mapBtn");
    if (!mapBtn) return;

    mapBtn.addEventListener("click", () => {
        if (!currentCity || !currentCity.lat || !currentCity.lon) return;
        const params = new URLSearchParams({
            name: currentCity.name,
            lat: String(currentCity.lat),
            lon: String(currentCity.lon),
        });
        window.open(`map.html?${params.toString()}`, "_blank");
    });
}

function registerPwa() {
    if (!("serviceWorker" in navigator)) {
        return;
    }

    if (isLocalDevelopment) {
        navigator.serviceWorker
            .getRegistrations()
            .then(registrations => Promise.all(registrations.map(registration => registration.unregister())))
            .catch(() => {});
        return;
    }

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

function registerCityInputWakeUp(input) {
    let warmedUp = false;

    input.addEventListener("focus", () => {
        if (warmedUp) return;
        warmedUp = true;
        warmCitiesSearch();
    });
}

document.addEventListener("DOMContentLoaded", async () => {
    const input = document.getElementById("cityInput");
    const searchBtn = document.getElementById("searchBtn");
    const autocompleteList = document.getElementById("autocompleteList");
    const clearRecentsBtn = document.getElementById("clearRecentsBtn");

    renderSavedCities();
    registerFavoriteButton();
    registerMapButton();
    registerPwa();
    initializeSupporterWidget();
    initializePush();
    registerCityInputSelection(input);
    registerCityInputWakeUp(input);

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
        getSuggestions: (query, options = {}) => searchCities(query, 8, "comuni", options),
        onSelect: executeSearch,
    });
});
