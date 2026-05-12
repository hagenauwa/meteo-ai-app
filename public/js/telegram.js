const BACKEND_URL = window.BACKEND_URL || "http://localhost:8000";
const TELEGRAM_CODE_KEY = "le_previsioni_telegram_code_v1";

let telegramPollingInterval = null;

export async function initializeTelegram() {
    const btn = document.getElementById("telegramToggle");
    if (!btn) return;

    btn.addEventListener("click", handleTelegramToggle);

    // Ripristina stato se c'è un codice salvato
    const savedCode = localStorage.getItem(TELEGRAM_CODE_KEY);
    if (savedCode) {
        const status = await checkTelegramStatus(savedCode);
        if (status.linked) {
            showTelegramLinked(status);
        } else {
            showTelegramPending(savedCode);
        }
    }
}

async function handleTelegramToggle() {
    const panel = document.getElementById("telegramPanel");
    if (!panel) return;

    if (panel.classList.contains("hidden")) {
        panel.classList.remove("hidden");
        await refreshTelegramState();
    } else {
        panel.classList.add("hidden");
        stopPolling();
    }
}

async function refreshTelegramState() {
    const savedCode = localStorage.getItem(TELEGRAM_CODE_KEY);

    if (savedCode) {
        const status = await checkTelegramStatus(savedCode);
        if (status.linked) {
            showTelegramLinked(status);
            return;
        }
    }

    showTelegramDisconnected();
}

function showTelegramDisconnected() {
    const content = document.getElementById("telegramContent");
    if (!content) return;

    stopPolling();

    content.innerHTML = `
        <div class="telegram-disconnected">
            <p>Collega il tuo account Telegram per ricevere notifiche direttamente su Telegram.</p>
            <button id="telegramLinkBtn" class="btn-primary telegram-link-btn">
                <i class="fab fa-telegram-plane"></i>
                <span>Genera codice di collegamento</span>
            </button>
        </div>
    `;

    document.getElementById("telegramLinkBtn")?.addEventListener("click", generateLinkCode);
}

async function generateLinkCode() {
    const content = document.getElementById("telegramContent");
    if (!content) return;

    try {
        const response = await fetch(`${BACKEND_URL}/api/telegram/link-code`, {
            method: "POST",
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || "Errore nella generazione del codice");
        }

        const data = await response.json();
        const code = data.linking_code;

        localStorage.setItem(TELEGRAM_CODE_KEY, code);
        showTelegramPending(code);
    } catch (err) {
        content.innerHTML = `
            <div class="telegram-error">
                <p><i class="fas fa-exclamation-triangle"></i> ${err.message}</p>
                <button id="telegramRetryBtn" class="btn-secondary">Riprova</button>
            </div>
        `;
        document.getElementById("telegramRetryBtn")?.addEventListener("click", generateLinkCode);
    }
}

function showTelegramPending(code) {
    const content = document.getElementById("telegramContent");
    if (!content) return;

    content.innerHTML = `
        <div class="telegram-pending">
            <p class="telegram-instruction">Invia questo codice al bot Telegram:</p>
            <div class="telegram-code-display">
                <code id="telegramCode">${code}</code>
                <button id="telegramCopyBtn" class="icon-btn-sm" title="Copia codice">
                    <i class="fas fa-copy"></i>
                </button>
            </div>
            <p class="telegram-steps">
                1. Apri <a href="https://t.me/LePrevisioniBot" target="_blank" rel="noopener">@LePrevisioniBot</a> su Telegram<br>
                2. Invia: <code>/start ${code}</code>
            </p>
            <div class="telegram-waiting">
                <div class="spinner-sm"></div>
                <span>In attesa del collegamento...</span>
            </div>
            <button id="telegramCancelBtn" class="btn-secondary btn-sm">Annulla</button>
        </div>
    `;

    document.getElementById("telegramCopyBtn")?.addEventListener("click", () => {
        navigator.clipboard.writeText(code).then(() => {
            const btn = document.getElementById("telegramCopyBtn");
            btn.innerHTML = '<i class="fas fa-check"></i>';
            setTimeout(() => { btn.innerHTML = '<i class="fas fa-copy"></i>'; }, 2000);
        });
    });

    document.getElementById("telegramCancelBtn")?.addEventListener("click", () => {
        localStorage.removeItem(TELEGRAM_CODE_KEY);
        stopPolling();
        showTelegramDisconnected();
    });

    // Polling per verificare il collegamento
    startPolling(code);
}

function showTelegramLinked(status) {
    const content = document.getElementById("telegramContent");
    const btn = document.getElementById("telegramToggle");
    if (!content) return;

    stopPolling();

    if (btn) btn.classList.add("is-active");

    const savedCode = localStorage.getItem(TELEGRAM_CODE_KEY);

    content.innerHTML = `
        <div class="telegram-linked">
            <div class="telegram-status-header">
                <i class="fas fa-check-circle telegram-check-icon"></i>
                <span>Telegram collegato</span>
            </div>
            ${status.user_name ? `<p class="telegram-username">@${status.user_name}</p>` : ''}

            <div class="telegram-preferences">
                <h4>Preferenze notifiche</h4>

                <div class="telegram-pref-item">
                    <label class="telegram-toggle-label">
                        <input type="checkbox" id="tgRainAlerts" ${status.rain_alerts_enabled ? 'checked' : ''}>
                        <span class="telegram-toggle-slider"></span>
                        <span>Allerte pioggia</span>
                    </label>
                </div>

                <div class="telegram-pref-item">
                    <label class="telegram-toggle-label">
                        <input type="checkbox" id="tgDailyForecast" ${status.daily_forecast_enabled ? 'checked' : ''}>
                        <span class="telegram-toggle-slider"></span>
                        <span>Promemoria giornaliero</span>
                    </label>
                </div>

                <div class="telegram-pref-item telegram-hour-picker" id="tgHourPicker" style="${status.daily_forecast_enabled ? '' : 'display:none'}">
                    <label>Ora promemoria:</label>
                    <select id="tgForecastHour">
                        ${Array.from({length: 24}, (_, i) =>
                            `<option value="${i}" ${i === status.daily_forecast_hour ? 'selected' : ''}>${String(i).padStart(2, '0')}:00</option>`
                        ).join('')}
                    </select>
                </div>

                <div class="telegram-pref-item">
                    <label>Città:</label>
                    <input type="text" id="tgCity" value="${status.city || ''}" placeholder="Es. Roma" class="telegram-city-input">
                </div>

                <button id="telegramSaveBtn" class="btn-primary btn-sm telegram-save-btn">
                    <i class="fas fa-save"></i> Salva preferenze
                </button>
                <span id="telegramSaveMsg" class="telegram-save-msg"></span>
            </div>

            <button id="telegramUnlinkBtn" class="btn-secondary btn-sm telegram-unlink-btn">
                <i class="fas fa-unlink"></i> Scollega Telegram
            </button>
        </div>
    `;

    // Event listeners
    document.getElementById("tgDailyForecast")?.addEventListener("change", (e) => {
        const hourPicker = document.getElementById("tgHourPicker");
        if (hourPicker) hourPicker.style.display = e.target.checked ? '' : 'none';
    });

    document.getElementById("telegramSaveBtn")?.addEventListener("click", async () => {
        await savePreferences(savedCode);
    });

    document.getElementById("telegramUnlinkBtn")?.addEventListener("click", async () => {
        await unlinkTelegram(savedCode);
    });
}

async function savePreferences(linkingCode) {
    const msg = document.getElementById("telegramSaveMsg");
    if (!linkingCode) return;

    const preferences = {
        rain_alerts_enabled: document.getElementById("tgRainAlerts")?.checked || false,
        daily_forecast_enabled: document.getElementById("tgDailyForecast")?.checked || false,
        daily_forecast_hour: parseInt(document.getElementById("tgForecastHour")?.value || "7", 10),
        city: document.getElementById("tgCity")?.value?.trim() || null,
    };

    try {
        const response = await fetch(`${BACKEND_URL}/api/telegram/preferences?linking_code=${encodeURIComponent(linkingCode)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(preferences),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || "Errore nel salvataggio");
        }

        if (msg) {
            msg.textContent = "Salvato!";
            msg.classList.add("success");
            setTimeout(() => { msg.textContent = ""; msg.classList.remove("success"); }, 2000);
        }
    } catch (err) {
        if (msg) {
            msg.textContent = err.message;
            msg.classList.add("error");
            setTimeout(() => { msg.textContent = ""; msg.classList.remove("error"); }, 3000);
        }
    }
}

async function unlinkTelegram(linkingCode) {
    if (!linkingCode) return;
    if (!confirm("Vuoi davvero scollegare Telegram?")) return;

    try {
        await fetch(`${BACKEND_URL}/api/telegram/unlink?linking_code=${encodeURIComponent(linkingCode)}`, {
            method: "POST",
        });

        localStorage.removeItem(TELEGRAM_CODE_KEY);
        const btn = document.getElementById("telegramToggle");
        if (btn) btn.classList.remove("is-active");
        showTelegramDisconnected();
    } catch (err) {
        console.error("Errore scollegamento Telegram:", err);
    }
}

async function checkTelegramStatus(linkingCode) {
    try {
        const response = await fetch(
            `${BACKEND_URL}/api/telegram/status?linking_code=${encodeURIComponent(linkingCode)}`
        );
        if (!response.ok) return { linked: false };
        return await response.json();
    } catch {
        return { linked: false };
    }
}

function startPolling(code) {
    stopPolling();
    telegramPollingInterval = setInterval(async () => {
        const status = await checkTelegramStatus(code);
        if (status.linked) {
            showTelegramLinked(status);
        }
    }, 3000); // ogni 3 secondi
}

function stopPolling() {
    if (telegramPollingInterval) {
        clearInterval(telegramPollingInterval);
        telegramPollingInterval = null;
    }
}
