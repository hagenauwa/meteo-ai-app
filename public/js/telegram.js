const BACKEND_URL = window.BACKEND_URL || "http://localhost:8000";
const TELEGRAM_CODE_KEY = "le_previsioni_telegram_code_v1";
const TELEGRAM_CLIENT_TOKEN_KEY = "le_previsioni_telegram_client_token_v1";
const TELEGRAM_PENDING_CODE_KEY = "le_previsioni_telegram_pending_code_v1";

const MAX_CONSECUTIVE_FAILURES = 5;
const POLL_INTERVAL_MS = 3000;

let telegramPollingInterval = null;
let consecutiveFailures = 0;
let isGeneratingLinkCode = false;
let linkCodeRequestId = 0;

export async function initializeTelegram() {
    const btn = document.getElementById("telegramToggle");
    if (!btn) return;

    btn.addEventListener("click", handleTelegramToggle);
    document.getElementById("telegramCloseBtn")?.addEventListener("click", stopPolling);

    // Clean up legacy code-only storage
    const legacyCode = localStorage.getItem(TELEGRAM_CODE_KEY);
    if (legacyCode) {
        localStorage.removeItem(TELEGRAM_CODE_KEY);
    }

    const clientToken = localStorage.getItem(TELEGRAM_CLIENT_TOKEN_KEY);
    if (clientToken) {
        const status = await checkTelegramStatus(clientToken);
        if (status.linked) {
            showTelegramLinked(status);
        } else if (status.state === "pending") {
            const pendingCode = localStorage.getItem(TELEGRAM_PENDING_CODE_KEY);
            if (pendingCode) {
                showTelegramPending(pendingCode, clientToken);
            } else {
                // Token exists but no pending code — likely linked but stale state
                showTelegramDisconnected("Collegamento precedente non verificabile: genera un nuovo codice.");
            }
        } else if (status.state === "expired") {
            localStorage.removeItem(TELEGRAM_CLIENT_TOKEN_KEY);
            localStorage.removeItem(TELEGRAM_PENDING_CODE_KEY);
            showTelegramDisconnected("Codice scaduto, genera un nuovo codice.");
        } else {
            // not_found, unlinked, error — clear stale data
            localStorage.removeItem(TELEGRAM_CLIENT_TOKEN_KEY);
            localStorage.removeItem(TELEGRAM_PENDING_CODE_KEY);
            showTelegramDisconnected();
        }
    } else if (legacyCode) {
        // Had legacy code but no client token — cannot verify, show disconnected
        showTelegramDisconnected("Collegamento precedente non verificabile: genera un nuovo codice.");
    }
}

async function handleTelegramToggle() {
    const panel = document.getElementById("telegramPanel");
    if (!panel) return;

    if (panel.classList.contains("hidden")) {
        panel.classList.remove("hidden");
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
        await refreshTelegramState();
    } else {
        panel.classList.add("hidden");
        stopPolling();
    }
}

async function refreshTelegramState() {
    const clientToken = localStorage.getItem(TELEGRAM_CLIENT_TOKEN_KEY);

    if (clientToken) {
        const status = await checkTelegramStatus(clientToken);
        if (status.linked) {
            showTelegramLinked(status);
            return;
        }
        if (status.state === "pending") {
            const pendingCode = localStorage.getItem(TELEGRAM_PENDING_CODE_KEY);
            if (pendingCode) {
                showTelegramPending(pendingCode, clientToken);
                return;
            }
        }
        // Token exists but not linked/pending — fall through to disconnected
    }

    showTelegramDisconnected();
}

function showTelegramDisconnected(message) {
    const content = document.getElementById("telegramContent");
    if (!content) return;

    stopPolling();

    const messageHtml = message ? `<p class="telegram-notice">${message}</p>` : "";

    content.innerHTML = `
        <div class="telegram-disconnected">
            ${messageHtml}
            <p>Collega il tuo account Telegram per ricevere notifiche direttamente su Telegram.</p>
            <button id="telegramLinkBtn" class="btn-primary telegram-link-btn">
                <i class="fab fa-telegram-plane"></i>
                <span>Genera codice di collegamento</span>
            </button>
        </div>
    `;

    document.getElementById("telegramLinkBtn")?.addEventListener("click", generateLinkCode);
}

async function generateLinkCode(event) {
    const content = document.getElementById("telegramContent");
    if (!content || isGeneratingLinkCode) return;

    isGeneratingLinkCode = true;
    const requestId = ++linkCodeRequestId;
    const trigger = event?.currentTarget;
    const triggerLabel = trigger?.querySelector?.("span") || trigger;
    const previousLabel = triggerLabel?.textContent || "";
    if (trigger) {
        trigger.disabled = true;
        trigger.setAttribute("aria-busy", "true");
    }
    if (triggerLabel) {
        triggerLabel.textContent = "Genero codice...";
    }

    try {
        const response = await fetch(`${BACKEND_URL}/api/telegram/link-code`, {
            method: "POST",
        });

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            const error = data;
            throw new Error(error.detail || "Errore nella generazione del codice");
        }

        const code = typeof data.linking_code === "string" ? data.linking_code.trim() : "";
        const clientToken = typeof data.client_token === "string" ? data.client_token.trim() : "";
        if (!code || !clientToken) {
            throw new Error("Risposta non valida, riprova");
        }

        if (requestId !== linkCodeRequestId) return;

        localStorage.setItem(TELEGRAM_CLIENT_TOKEN_KEY, clientToken);
        localStorage.setItem(TELEGRAM_PENDING_CODE_KEY, code);
        // Clean up legacy key if it still exists
        localStorage.removeItem(TELEGRAM_CODE_KEY);

        showTelegramPending(code, clientToken);
    } catch (err) {
        if (requestId !== linkCodeRequestId) return;
        content.innerHTML = `
            <div class="telegram-error">
                <p><i class="fas fa-exclamation-triangle"></i> ${err.message}</p>
                <button id="telegramRetryBtn" class="btn-secondary">Riprova</button>
            </div>
        `;
        document.getElementById("telegramRetryBtn")?.addEventListener("click", generateLinkCode);
    } finally {
        if (requestId === linkCodeRequestId) {
            isGeneratingLinkCode = false;
        }
        if (trigger?.isConnected) {
            trigger.disabled = false;
            trigger.removeAttribute("aria-busy");
        }
        if (triggerLabel?.isConnected) {
            triggerLabel.textContent = previousLabel;
        }
    }
}

function showTelegramPending(code, clientToken) {
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
        localStorage.removeItem(TELEGRAM_CLIENT_TOKEN_KEY);
        localStorage.removeItem(TELEGRAM_PENDING_CODE_KEY);
        stopPolling();
        showTelegramDisconnected();
    });

    startPolling(clientToken);
}

function showTelegramLinked(status) {
    const content = document.getElementById("telegramContent");
    const btn = document.getElementById("telegramToggle");
    if (!content) return;

    stopPolling();

    // Clear pending code but keep client token
    localStorage.removeItem(TELEGRAM_PENDING_CODE_KEY);

    if (btn) btn.classList.add("is-active");

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

    document.getElementById("tgDailyForecast")?.addEventListener("change", (e) => {
        const hourPicker = document.getElementById("tgHourPicker");
        if (hourPicker) hourPicker.style.display = e.target.checked ? '' : 'none';
    });

    document.getElementById("telegramSaveBtn")?.addEventListener("click", async () => {
        await savePreferences();
    });

    document.getElementById("telegramUnlinkBtn")?.addEventListener("click", async () => {
        await unlinkTelegram();
    });
}

async function savePreferences() {
    const clientToken = localStorage.getItem(TELEGRAM_CLIENT_TOKEN_KEY);
    const msg = document.getElementById("telegramSaveMsg");
    if (!clientToken) return;

    const preferences = {
        rain_alerts_enabled: document.getElementById("tgRainAlerts")?.checked || false,
        daily_forecast_enabled: document.getElementById("tgDailyForecast")?.checked || false,
        daily_forecast_hour: parseInt(document.getElementById("tgForecastHour")?.value || "7", 10),
        city: document.getElementById("tgCity")?.value?.trim() || null,
    };

    try {
        const response = await fetch(`${BACKEND_URL}/api/telegram/preferences`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Telegram-Client-Token": clientToken,
            },
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

async function unlinkTelegram() {
    const clientToken = localStorage.getItem(TELEGRAM_CLIENT_TOKEN_KEY);
    if (!clientToken) return;
    if (!confirm("Vuoi davvero scollegare Telegram?")) return;

    try {
        await fetch(`${BACKEND_URL}/api/telegram/unlink`, {
            method: "POST",
            headers: {
                "X-Telegram-Client-Token": clientToken,
            },
        });

        localStorage.removeItem(TELEGRAM_CLIENT_TOKEN_KEY);
        localStorage.removeItem(TELEGRAM_PENDING_CODE_KEY);
        const btn = document.getElementById("telegramToggle");
        if (btn) btn.classList.remove("is-active");
        showTelegramDisconnected();
    } catch (err) {
        console.error("Errore scollegamento Telegram:", err);
    }
}

async function checkTelegramStatus(clientToken) {
    try {
        const response = await fetch(`${BACKEND_URL}/api/telegram/status`, {
            headers: {
                "X-Telegram-Client-Token": clientToken,
            },
        });
        if (!response.ok) {
            return { linked: false, state: "error" };
        }
        return await response.json();
    } catch {
        return { linked: false, state: "error" };
    }
}

function startPolling(clientToken) {
    stopPolling();
    consecutiveFailures = 0;

    telegramPollingInterval = setInterval(async () => {
        const status = await checkTelegramStatus(clientToken);

        // Network error — track consecutive failures
        if (status.state === "error") {
            consecutiveFailures++;
            if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
                stopPolling();
                showTelegramError("Errore di connessione, riprova");
            }
            return;
        }

        // Reset failure counter on successful response
        consecutiveFailures = 0;

        if (status.linked) {
            showTelegramLinked(status);
            return;
        }

        // Handle terminal non-linked states
        if (status.state === "expired") {
            stopPolling();
            localStorage.removeItem(TELEGRAM_CLIENT_TOKEN_KEY);
            localStorage.removeItem(TELEGRAM_PENDING_CODE_KEY);
            showTelegramExpired();
            return;
        }

        if (status.state === "not_found" || status.state === "unlinked") {
            stopPolling();
            localStorage.removeItem(TELEGRAM_CLIENT_TOKEN_KEY);
            localStorage.removeItem(TELEGRAM_PENDING_CODE_KEY);
            showTelegramDisconnected();
            return;
        }

        // state === "pending" — keep polling
    }, POLL_INTERVAL_MS);
}

function stopPolling() {
    if (telegramPollingInterval) {
        clearInterval(telegramPollingInterval);
        telegramPollingInterval = null;
    }
}

function showTelegramExpired() {
    const content = document.getElementById("telegramContent");
    if (!content) return;

    stopPolling();

    content.innerHTML = `
        <div class="telegram-disconnected">
            <p><i class="fas fa-clock"></i> Codice scaduto, genera un nuovo codice.</p>
            <button id="telegramLinkBtn" class="btn-primary telegram-link-btn">
                <i class="fab fa-telegram-plane"></i>
                <span>Genera nuovo codice</span>
            </button>
        </div>
    `;

    document.getElementById("telegramLinkBtn")?.addEventListener("click", generateLinkCode);
}

function showTelegramError(message) {
    const content = document.getElementById("telegramContent");
    if (!content) return;

    stopPolling();

    content.innerHTML = `
        <div class="telegram-error">
            <p><i class="fas fa-exclamation-triangle"></i> ${message}</p>
            <button id="telegramRetryBtn" class="btn-secondary">Riprova</button>
        </div>
    `;

    document.getElementById("telegramRetryBtn")?.addEventListener("click", async () => {
        const clientToken = localStorage.getItem(TELEGRAM_CLIENT_TOKEN_KEY);
        if (clientToken) {
            const status = await checkTelegramStatus(clientToken);
            if (status.linked) {
                showTelegramLinked(status);
                return;
            }
            if (status.state === "pending") {
                const pendingCode = localStorage.getItem(TELEGRAM_PENDING_CODE_KEY);
                if (pendingCode) {
                    showTelegramPending(pendingCode, clientToken);
                    return;
                }
            }
        }
        // Token lost or invalid — start fresh
        showTelegramDisconnected();
    });
}
