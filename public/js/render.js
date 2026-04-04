import { WEATHER_ICONS } from "./config.js";

function formatDate(date, options = {}) {
    return new Date(date).toLocaleDateString("it-IT", {
        weekday: "long",
        day: "numeric",
        month: "long",
        ...options,
    });
}

function formatTime(date) {
    return new Date(date).toLocaleTimeString("it-IT", {
        hour: "2-digit",
        minute: "2-digit",
    });
}

function formatShortDay(date) {
    return new Date(date).toLocaleDateString("it-IT", {
        weekday: "short",
    });
}

function formatShortDate(date) {
    return new Date(date).toLocaleDateString("it-IT", {
        day: "numeric",
        month: "short",
    });
}

function getWeatherIcon(iconCode) {
    return WEATHER_ICONS[iconCode] || "fa-cloud";
}

function getRelativeDayLabel(index, date) {
    if (index === 0) return "Oggi";
    if (index === 1) return "Domani";
    return formatDate(date, { weekday: "long", day: "numeric", month: "long" });
}

function buildDayTag(day) {
    if (day.ml?.badge) return day.ml.badge;
    if ((day.pop || 0) >= 0.6) return "Possibili piogge";
    if ((day.wind_speed || 0) >= 28) return "Vento deciso";
    if ((day.weather?.[0]?.description || "").toLowerCase().includes("nuvol")) return "Cielo variabile";
    return "Giornata stabile";
}

function buildDaySummary(day) {
    if (day.ml?.summary) return day.ml.summary;

    const description = day.weather?.[0]?.description || "Condizioni variabili";
    const rainPct = Math.round((day.pop || 0) * 100);
    const wind = Math.round(day.wind_speed || 0);

    if (rainPct >= 60) {
        return `${description}. Ombrello consigliato: la probabilita di pioggia e intorno al ${rainPct}%.`;
    }
    if (wind >= 28) {
        return `${description}. Attenzione a raffiche piu presenti, con vento fino a ${wind} km/h.`;
    }
    if (rainPct >= 30) {
        return `${description}. Possibili passaggi instabili, ma con fasi asciutte prevalenti.`;
    }
    return `${description}. Scenario nel complesso regolare per la giornata selezionata.`;
}

function setText(id, value) {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
}

function renderPlannerHead(payload, selectedDay, selectedIndex) {
    setText("cityName", payload.name || "--");

    const cityMeta = payload.city
        ? [payload.city.province, payload.city.region].filter(Boolean).join(" • ")
        : "Italia";
    setText("cityMeta", cityMeta || "Italia");
    setText("selectedDayLabel", getRelativeDayLabel(selectedIndex, selectedDay.dt));
    setText("selectedDayDate", formatDate(selectedDay.dt));

    const badge = document.getElementById("forecastBadge");
    const mlReady = Boolean(
        payload.ml?.summary?.model_ready ||
        payload.ml?.summary?.condition_model_ready ||
        payload.ml?.rain_prediction?.model_ready
    );
    badge.classList.toggle("hidden", !mlReady);
}

function renderDaySelector(daily, selectedIndex, onDaySelect) {
    const container = document.getElementById("daySelector");
    container.innerHTML = "";

    daily.forEach((day, index) => {
        const adjusted = day.ml?.adjusted_temp_range || day.temp;
        const button = document.createElement("button");
        button.type = "button";
        button.className = `day-pill${index === selectedIndex ? " active" : ""}`;
        button.innerHTML = `
            <span class="day-pill-top">${index === 0 ? "Oggi" : formatShortDay(day.dt)}</span>
            <span class="day-pill-date">${formatShortDate(day.dt)}</span>
            <span class="day-pill-temp">${Math.round(adjusted.max)}° / ${Math.round(adjusted.min)}°</span>
        `;
        button.addEventListener("click", () => onDaySelect(index));
        container.appendChild(button);
    });
}

function renderSelectedDay(day) {
    const mlDay = day.ml || {};
    const adjusted = mlDay.adjusted_temp_range || day.temp;
    const displayCondition = mlDay.display_condition || day.weather?.[0]?.description || "--";
    const rainProbability = mlDay.rain_probability ?? day.pop ?? 0;

    setText("selectedDayDate", formatDate(day.dt));
    setText("selectedDayDescription", displayCondition);
    setText("selectedDaySummary", buildDaySummary(day));
    setText("selectedDayMax", `${Math.round(adjusted.max)}°`);
    setText("selectedDayMin", `${Math.round(adjusted.min)}°`);
    setText("selectedDayRain", `${Math.round(rainProbability * 100)}%`);
    setText("selectedDayWind", `${Math.round(day.wind_speed || 0)} km/h`);
    setText("selectedDayTag", buildDayTag(day));

    const icon = document.getElementById("selectedDayIcon");
    icon.className = `fas ${getWeatherIcon(day.weather?.[0]?.icon)}`;
}

function renderCurrent(payload) {
    const { current } = payload;
    const correction = payload.ml?.correction || { corrected_temp: current.temp };

    setText("currentDate", `Aggiornato ${formatDate(new Date(), { weekday: "long" })}`);
    setText("currentTemp", Math.round(correction.corrected_temp ?? current.temp));
    setText("weatherDescription", current.weather?.[0]?.description || "--");
    setText("humidity", `${current.humidity}%`);
    setText("windSpeed", `${Math.round(current.wind_speed)} km/h`);
    setText("visibility", `${(current.visibility / 1000).toFixed(1)} km`);
    setText("pressure", `${current.pressure} hPa`);

    const icon = document.getElementById("weatherIcon");
    icon.className = `fas ${getWeatherIcon(current.weather?.[0]?.icon)}`;
}

function renderHourlyDetail(selectedDay, hourly) {
    const container = document.getElementById("hourlyForecast");
    const hint = document.getElementById("hourlyHint");
    const section = document.getElementById("hourlySection");
    const hoursForDay = hourly.filter(hour => String(hour.dt || "").startsWith(selectedDay.dt));

    container.innerHTML = "";
    section.classList.remove("is-empty");

    if (!hoursForDay.length) {
        hint.textContent = "Per questa data e disponibile solo il riepilogo giornaliero.";
        section.classList.add("is-empty");

        const empty = document.createElement("div");
        empty.className = "empty-forecast";
        empty.textContent = "Il dettaglio ora per ora arrivera quando il backend esporra un orizzonte piu ampio.";
        container.appendChild(empty);
        return;
    }

    hint.textContent = "Scansione oraria disponibile nel breve termine.";

    hoursForDay.forEach(hour => {
        const card = document.createElement("article");
        card.className = "hour-card";
        card.innerHTML = `
            <span class="time">${formatTime(hour.dt)}</span>
            <i class="fas ${getWeatherIcon(hour.weather?.[0]?.icon)}"></i>
            <strong class="temp">${Math.round(hour.temp)}°</strong>
            <span class="rain">Pioggia ${Math.round((hour.pop || 0) * 100)}%</span>
        `;
        container.appendChild(card);
    });
}

function renderModelNote(payload) {
    const note = document.getElementById("modelNote");
    const mlReady = Boolean(
        payload.ml?.summary?.model_ready ||
        payload.ml?.summary?.condition_model_ready ||
        payload.ml?.rain_prediction?.model_ready
    );
    note.textContent = mlReady
        ? "Le previsioni vengono affinate automaticamente usando osservazioni meteo reali, nuvolosita e vento."
        : "Le previsioni vengono aggiornate automaticamente con osservazioni meteo recenti.";
}

export function showLoading(show) {
    const loadingEl = document.getElementById("loadingState");
    const resultsEl = document.getElementById("weatherResults");
    const errorEl = document.getElementById("errorMessage");

    if (show) {
        loadingEl.classList.remove("hidden");
        resultsEl.classList.add("hidden");
        errorEl.classList.add("hidden");
    } else {
        loadingEl.classList.add("hidden");
    }
}

export function showError(message) {
    const errorEl = document.getElementById("errorMessage");
    const errorText = document.getElementById("errorText");
    errorText.textContent = message;
    errorEl.classList.remove("hidden");
    document.getElementById("weatherResults").classList.add("hidden");
    showLoading(false);
}

export function hideError() {
    document.getElementById("errorMessage").classList.add("hidden");
}

export function renderWeather(payload, { selectedDayIndex = 0, onDaySelect = () => {} } = {}) {
    const daily = payload.daily || [];
    if (!daily.length) {
        showError("La previsione giornaliera non e disponibile per questa citta.");
        return;
    }

    const safeIndex = Math.min(Math.max(selectedDayIndex, 0), daily.length - 1);
    const selectedDay = daily[safeIndex];

    renderPlannerHead(payload, selectedDay, safeIndex);
    renderDaySelector(daily, safeIndex, onDaySelect);
    renderSelectedDay(selectedDay);
    renderCurrent(payload);
    renderHourlyDetail(selectedDay, payload.hourly || []);
    renderModelNote(payload);

    document.getElementById("weatherResults").classList.remove("hidden");
    showLoading(false);
}

export function renderChipList(targetId, cities, onClick, { onRemove = null } = {}) {
    const container = document.getElementById(targetId);
    if (!container) return;
    container.innerHTML = "";

    if (!cities.length) {
        container.innerHTML = '<span class="city-chip is-empty">Nessuna</span>';
        return;
    }

    cities.forEach(city => {
        if (onRemove) {
            const row = document.createElement("div");
            row.className = "city-chip-row";

            const button = document.createElement("button");
            button.className = "city-chip-main";
            button.type = "button";
            button.textContent = city.name;
            button.addEventListener("click", () => onClick(city));

            const removeButton = document.createElement("button");
            removeButton.className = "city-chip-remove";
            removeButton.type = "button";
            removeButton.setAttribute("aria-label", `Rimuovi ${city.name} dalle recenti`);
            removeButton.innerHTML = '<i class="fas fa-xmark" aria-hidden="true"></i>';
            removeButton.addEventListener("click", event => {
                event.stopPropagation();
                onRemove(city);
            });

            row.append(button, removeButton);
            container.appendChild(row);
            return;
        }

        const button = document.createElement("button");
        button.className = "city-chip";
        button.type = "button";
        button.textContent = city.name;
        button.addEventListener("click", () => onClick(city));
        container.appendChild(button);
    });
}
