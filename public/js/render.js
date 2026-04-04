import { WEATHER_ICONS } from "./config.js";

function formatDate(date, options = {}) {
    return new Date(date).toLocaleDateString("it-IT", {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
        ...options,
    });
}

function formatTime(date) {
    return new Date(date).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
}

function getWeatherIcon(iconCode) {
    return WEATHER_ICONS[iconCode] || "fa-cloud";
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
    showLoading(false);
}

export function hideError() {
    document.getElementById("errorMessage").classList.add("hidden");
}

function renderCurrent(payload) {
    const { current } = payload;
    const correction = payload.ml?.correction || { correction: 0, corrected_temp: current.temp };
    const rain = payload.ml?.rain_prediction || { model_ready: false };

    document.getElementById("cityName").textContent = payload.name;
    document.getElementById("currentDate").textContent = formatDate(new Date());
    document.getElementById("currentTemp").textContent = Math.round(correction.corrected_temp ?? current.temp);
    document.getElementById("weatherIcon").className = `fas ${getWeatherIcon(current.weather?.[0]?.icon)}`;
    document.getElementById("weatherDescription").textContent = current.weather?.[0]?.description || "--";

    const correctionEl = document.getElementById("aiCorrection");
    if (correction.model_ready && Math.abs(correction.correction || 0) > 0.2) {
        correctionEl.classList.remove("hidden");
        const sign = correction.correction > 0 ? "+" : "";
        document.getElementById("correctionValue").textContent = `${sign}${correction.correction.toFixed(1)}`;
    } else {
        correctionEl.classList.add("hidden");
    }

    const rainWidget = document.getElementById("mlRainPrediction");
    if (rain.model_ready) {
        const pct = Math.round((rain.rain_probability || 0) * 100);
        document.getElementById("rainPct").textContent = `${pct}%`;
        const rainBar = document.getElementById("rainBar");
        rainBar.style.width = `${pct}%`;
        rainBar.style.background = pct < 30 ? "#10b981" : pct < 60 ? "#f59e0b" : "#3b82f6";
        document.getElementById("rainLabel").textContent = rain.will_rain
            ? `Probabile pioggia — confidenza ${rain.confidence}`
            : `Scenario asciutto — confidenza ${rain.confidence}`;
        rainWidget.classList.remove("hidden");
    } else {
        rainWidget.classList.add("hidden");
    }

    document.getElementById("humidity").textContent = `${current.humidity}%`;
    document.getElementById("windSpeed").textContent = `${Math.round(current.wind_speed)} km/h`;
    document.getElementById("visibility").textContent = `${(current.visibility / 1000).toFixed(1)} km`;
    document.getElementById("pressure").textContent = `${current.pressure} hPa`;
}

function renderHourly(hourly) {
    const container = document.getElementById("hourlyForecast");
    container.innerHTML = "";
    hourly.slice(0, 24).forEach(hour => {
        const card = document.createElement("div");
        card.className = "hour-card";
        card.innerHTML = `
            <div class="time">${formatTime(hour.dt)}</div>
            <i class="fas ${getWeatherIcon(hour.weather?.[0]?.icon)}"></i>
            <div class="temp">${Math.round(hour.temp)}°</div>
        `;
        container.appendChild(card);
    });
}

function renderDaily(daily) {
    const container = document.getElementById("dailyForecast");
    container.innerHTML = "";
    daily.slice(1, 6).forEach(day => {
        const date = new Date(day.dt);
        const card = document.createElement("div");
        card.className = "day-card";
        card.innerHTML = `
            <div class="day-name">${date.toLocaleDateString("it-IT", { weekday: "short" })}</div>
            <div class="day-date">${date.toLocaleDateString("it-IT", { day: "numeric", month: "short" })}</div>
            <i class="fas ${getWeatherIcon(day.weather?.[0]?.icon)}"></i>
            <div class="temp-range">
                <span class="temp-max">${Math.round(day.temp.max)}°</span>
                <span class="temp-min">${Math.round(day.temp.min)}°</span>
            </div>
        `;
        container.appendChild(card);
    });
}

function renderErrorChart(stats) {
    const canvas = document.getElementById("errorChart");
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const dataset = stats?.lead_time_error || [];
    if (!dataset.length) {
        ctx.fillStyle = "#94a3b8";
        ctx.font = "14px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Storico ML ancora in costruzione...", canvas.width / 2, canvas.height / 2);
        return;
    }

    const padding = 40;
    const chartWidth = canvas.width - padding * 2;
    const chartHeight = canvas.height - padding * 2;
    const maxValue = Math.max(...dataset.map(item => item.avg_abs_error), 1);
    const barWidth = chartWidth / dataset.length;

    ctx.strokeStyle = "#e2e8f0";
    ctx.beginPath();
    ctx.moveTo(padding, padding);
    ctx.lineTo(padding, canvas.height - padding);
    ctx.lineTo(canvas.width - padding, canvas.height - padding);
    ctx.stroke();

    dataset.forEach((item, index) => {
        const height = (item.avg_abs_error / maxValue) * chartHeight;
        const x = padding + index * barWidth + barWidth * 0.15;
        const y = canvas.height - padding - height;
        ctx.fillStyle = "#3b82f6";
        ctx.fillRect(x, y, barWidth * 0.7, height);
        ctx.fillStyle = "#475569";
        ctx.font = "12px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(`${item.lead_hours}h`, x + barWidth * 0.35, canvas.height - padding + 16);
    });
}

function renderStats(payload) {
    const stats = payload.ml?.stats || {};
    document.getElementById("predictionsCount").textContent = stats.verified_predictions || 0;
    document.getElementById("avgError").textContent = stats.avg_error_celsius ?? "--";
    document.getElementById("modelStatus").textContent = stats.model_ready ? "Attivo" : "In attesa";

    const learning = stats.model_samples
        ? Math.min(100, Math.round((stats.model_samples / 500) * 100))
        : 0;
    document.getElementById("learningProgress").textContent = `${learning}%`;
    document.getElementById("mlModelInfo").textContent = stats.model_ready
        ? `Ridge + baseline temporale — MAE ${stats.model_mae?.toFixed?.(3) ?? stats.model_mae}°C`
        : "Modello in raccolta dati";

    renderErrorChart(stats);
}

export function renderWeather(payload) {
    renderCurrent(payload);
    renderHourly(payload.hourly || []);
    renderDaily(payload.daily || []);
    renderStats(payload);
    document.getElementById("weatherResults").classList.remove("hidden");
    showLoading(false);
}

export function renderChipList(targetId, cities, onClick) {
    const container = document.getElementById(targetId);
    if (!container) return;
    container.innerHTML = "";

    if (!cities.length) {
        container.innerHTML = '<span class="city-chip">Nessuna</span>';
        return;
    }

    cities.forEach(city => {
        const button = document.createElement("button");
        button.className = "city-chip";
        button.textContent = city.name;
        button.addEventListener("click", () => onClick(city));
        container.appendChild(button);
    });
}

export function addChatMessage(type, text) {
    const container = document.getElementById("chatMessages");
    if (!container) return;
    const msg = document.createElement("div");
    msg.className = `chat-message ${type}`;
    const icon = type === "bot" ? "fa-robot" : "fa-user";
    msg.innerHTML = `<i class="fas ${icon}"></i><div class="message-content">${text}</div>`;
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
}
