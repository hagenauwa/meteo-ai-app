import { WEATHER_ICONS } from "./config.js";

const CLOUDY_ICON_CODES = new Set(["02d", "02n", "03d", "03n", "04d", "04n"]);

function isNightIcon(iconCode) {
    return String(iconCode || "").endsWith("n");
}

function resolveWeatherVisual({ iconCode, rainProbability = 0, preferRainIcon = false } = {}) {
    let resolvedIconCode = iconCode || "03d";

    if (preferRainIcon && rainProbability >= 0.6 && CLOUDY_ICON_CODES.has(resolvedIconCode)) {
        resolvedIconCode = isNightIcon(resolvedIconCode) ? "10n" : "10d";
    }

    const iconClass = WEATHER_ICONS[resolvedIconCode] || "fa-cloud";

    if (resolvedIconCode === "01d") {
        return { iconClass, tone: "sun" };
    }
    if (resolvedIconCode === "01n") {
        return { iconClass, tone: "night" };
    }
    if (resolvedIconCode === "02d") {
        return { iconClass, tone: "partly-cloudy" };
    }
    if (resolvedIconCode === "02n") {
        return { iconClass, tone: "partly-cloudy-night" };
    }
    if (resolvedIconCode === "03d" || resolvedIconCode === "03n" || resolvedIconCode === "04d" || resolvedIconCode === "04n") {
        return { iconClass, tone: "cloud" };
    }
    if (resolvedIconCode === "09d" || resolvedIconCode === "09n" || resolvedIconCode === "10d" || resolvedIconCode === "10n") {
        return { iconClass, tone: "rain" };
    }
    if (resolvedIconCode === "11d" || resolvedIconCode === "11n") {
        return { iconClass, tone: "storm" };
    }
    if (resolvedIconCode === "13d" || resolvedIconCode === "13n") {
        return { iconClass, tone: "snow" };
    }
    if (resolvedIconCode === "50d" || resolvedIconCode === "50n") {
        return { iconClass, tone: "fog" };
    }

    return { iconClass, tone: "cloud" };
}

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

function applyWeatherVisual(node, options) {
    if (!node) return;
    const { iconClass, tone } = resolveWeatherVisual(options);
    node.className = `fas weather-icon weather-icon--${tone} ${iconClass}`;
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
        return `${description}. Ombrello consigliato: la probabilità di pioggia è intorno al ${rainPct}%.`;
    }
    if (wind >= 28) {
        return `${description}. Attenzione a raffiche più presenti, con vento fino a ${wind} km/h.`;
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

        const topSpan = document.createElement("span");
        topSpan.className = "day-pill-top";
        topSpan.textContent = index === 0 ? "Oggi" : formatShortDay(day.dt);

        const dateSpan = document.createElement("span");
        dateSpan.className = "day-pill-date";
        dateSpan.textContent = formatShortDate(day.dt);

        const tempSpan = document.createElement("span");
        tempSpan.className = "day-pill-temp";
        tempSpan.textContent = `${Math.round(adjusted.max)}° / ${Math.round(adjusted.min)}°`;

        button.appendChild(topSpan);
        button.appendChild(dateSpan);
        button.appendChild(tempSpan);
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
    applyWeatherVisual(icon, {
        iconCode: day.weather?.[0]?.icon,
        rainProbability,
    });
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
    applyWeatherVisual(icon, {
        iconCode: current.weather?.[0]?.icon,
        rainProbability: current.pop || 0,
        preferRainIcon: true,
    });
}

function renderHourlyDetail(selectedDay, hourly) {
    const container = document.getElementById("hourlyForecast");
    const hint = document.getElementById("hourlyHint");
    const section = document.getElementById("hourlySection");
    const hoursForDay = hourly.filter(hour => String(hour.dt || "").startsWith(selectedDay.dt));

    container.innerHTML = "";
    section.classList.remove("is-empty");

    if (!hoursForDay.length) {
        hint.textContent = "Per questa data è disponibile solo il riepilogo giornaliero.";
        section.classList.add("is-empty");

        const empty = document.createElement("div");
        empty.className = "empty-forecast";
        empty.textContent = "Il dettaglio ora per ora arriverà quando il backend esporrà un orizzonte più ampio.";
        container.appendChild(empty);
        return;
    }

    hint.textContent = "Scansione oraria disponibile nel breve termine.";

    hoursForDay.forEach(hour => {
        const card = document.createElement("article");
        card.className = "hour-card";
        const { iconClass, tone } = resolveWeatherVisual({
            iconCode: hour.weather?.[0]?.icon,
            rainProbability: hour.pop || 0,
            preferRainIcon: true,
        });
        const timeSpan = document.createElement("span");
        timeSpan.className = "time";
        timeSpan.textContent = formatTime(hour.dt);

        const weatherIcon = document.createElement("i");
        weatherIcon.className = `fas weather-icon weather-icon--${tone} ${iconClass}`;

        const tempStrong = document.createElement("strong");
        tempStrong.className = "temp";
        tempStrong.textContent = `${Math.round(hour.temp)}°`;

        const rainSpan = document.createElement("span");
        rainSpan.className = "rain";
        rainSpan.textContent = `Pioggia ${Math.round((hour.pop || 0) * 100)}%`;

        card.appendChild(timeSpan);
        card.appendChild(weatherIcon);
        card.appendChild(tempStrong);
        card.appendChild(rainSpan);
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
        ? "Le previsioni vengono affinate automaticamente usando osservazioni meteo reali, nuvolosità e vento."
        : "Le previsioni vengono aggiornate automaticamente con osservazioni meteo recenti.";
}

function getUvColor(uv) {
    if (uv == null) return "";
    if (uv <= 2) return "uv-low";
    if (uv <= 5) return "uv-moderate";
    if (uv <= 7) return "uv-high";
    if (uv <= 10) return "uv-very-high";
    return "uv-extreme";
}

function getAqiLabel(eaqi) {
    if (eaqi == null) return "--";
    const labels = ["Eccellente", "Buona", "Moderata", "Scadente", "Pessima"];
    return labels[Math.min(Math.max(0, eaqi - 1), 4)] || "--";
}

function getAqiColor(eaqi) {
    if (eaqi == null) return "";
    if (eaqi <= 1) return "aqi-good";
    if (eaqi <= 2) return "aqi-moderate";
    if (eaqi <= 3) return "aqi-poor";
    if (eaqi <= 4) return "aqi-bad";
    return "aqi-very-bad";
}

export function renderAdvanced(payload) {
    const advanced = payload?.advanced;
    const uvNode = document.getElementById("uvIndex");
    const aqiNode = document.getElementById("airQuality");
    if (!uvNode || !aqiNode) return;

    if (advanced) {
        const uv = advanced.uv_index;
        const eaqi = advanced.european_aqi;
        uvNode.textContent = uv != null ? `${uv} ${getUvColor(uv).replace("uv-", "")}` : "--";
        uvNode.className = `value ${getUvColor(uv)}`;
        aqiNode.textContent = getAqiLabel(eaqi);
        aqiNode.className = `value ${getAqiColor(eaqi)}`;
    } else {
        uvNode.textContent = "--";
        aqiNode.textContent = "--";
    }
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
        showError("La previsione giornaliera non è disponibile per questa città.");
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
    renderAdvanced(payload);

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
