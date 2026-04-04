import {
    fetchWeatherByCity,
    hasAdminToken,
    loadCityIndex,
    searchCities,
    sendChat,
    triggerRunCycle,
    triggerTraining,
} from "./api.js";
import { createAutocomplete } from "./autocomplete.js";
import { initChat } from "./chat.js";
import { hideError, renderChipList, renderWeather, showError, showLoading } from "./render.js";
import { getFavorites, getLastCity, getRecents, pushRecent, toggleFavorite } from "./storage.js";

let currentCity = null;

function normalize(value) {
    return value
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "");
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
        currentCity = {
            name: payload.city?.name || payload.name,
            lat: payload.lat,
            lon: payload.lon,
            region: payload.city?.region || city.region || "",
            province: payload.city?.province || city.province || "",
        };
        pushRecent(currentCity);
        renderSavedCities();
        renderWeather(payload);
    } catch (error) {
        showError(error.message || "Errore durante la ricerca meteo");
    }
}

async function searchFromInput() {
    const input = document.getElementById("cityInput");
    const value = input.value.trim();
    if (!value) {
        showError("Inserisci il nome di una città");
        return;
    }

    try {
        const results = await searchCities(value, 1, "all");
        if (!results.length) {
            throw new Error(`Città "${value}" non trovata`);
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

function configureAdminControls() {
    const trainBtn = document.getElementById("trainModelBtn");
    const runCycleBtn = document.getElementById("verifyPredictionsBtn");
    const notice = document.getElementById("adminNotice");
    const adminEnabled = hasAdminToken();

    if (!adminEnabled) {
        trainBtn.disabled = true;
        runCycleBtn.disabled = true;
        notice.textContent = "Frontend pubblico in sola lettura: training e run-cycle sono protetti.";
        return;
    }

    notice.textContent = "Token admin attivo: controlli manuali disponibili.";

    trainBtn.addEventListener("click", async () => {
        trainBtn.disabled = true;
        try {
            const result = await triggerTraining();
            alert(
                `Training completato.\nMAE: ${result.mae?.toFixed?.(3) ?? result.mae}\nBaseline: ${
                    result.baseline_mae?.toFixed?.(3) ?? result.baseline_mae
                }`
            );
        } catch (error) {
            alert(error.message);
        } finally {
            trainBtn.disabled = false;
        }
    });

    runCycleBtn.addEventListener("click", async () => {
        runCycleBtn.disabled = true;
        try {
            const result = await triggerRunCycle();
            alert(result.message || "Ciclo avviato");
        } catch (error) {
            alert(error.message);
        } finally {
            runCycleBtn.disabled = false;
        }
    });
}

function registerFavoriteButton() {
    const button = document.getElementById("favoriteBtn");
    button.addEventListener("click", () => {
        if (!currentCity) {
            alert("Cerca prima una città da salvare.");
            return;
        }
        const added = toggleFavorite(currentCity);
        renderSavedCities();
        alert(added ? `${currentCity.name} aggiunta ai preferiti.` : `${currentCity.name} rimossa dai preferiti.`);
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
    const mlToggleHeader = document.getElementById("mlToggleHeader");
    const mlBody = document.getElementById("mlBody");

    if (mlToggleHeader && mlBody) {
        mlToggleHeader.addEventListener("click", () => {
            const isOpen = mlBody.classList.toggle("open");
            mlToggleHeader.classList.toggle("open", isOpen);
        });
    }

    renderSavedCities();
    configureAdminControls();
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

    initChat({
        cityIndex: loadCityIndex,
        sendChat,
        fetchWeatherByCity,
    });

    const lastCity = getLastCity();
    if (lastCity) {
        input.value = lastCity;
        await searchFromInput();
    }
});
