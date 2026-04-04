import {
    confirmSupporterSession,
    createSupporterCheckoutSession,
    getSupporterStatus,
} from "./api.js";
import {
    clearSupporterToken,
    getSupporterToken,
    setSupporterToken,
} from "./storage.js";

function cleanupSupporterParams() {
    const url = new URL(window.location.href);
    url.searchParams.delete("supporter_success");
    url.searchParams.delete("supporter_canceled");
    url.searchParams.delete("session_id");
    window.history.replaceState({}, document.title, url.pathname + url.search + url.hash);
}

function getElements() {
    return {
        form: document.getElementById("supporterForm"),
        prompt: document.getElementById("supporterPrompt"),
        thankYou: document.getElementById("supporterThankYou"),
        thankYouText: document.getElementById("supporterThankYouText"),
        email: document.getElementById("supporterEmail"),
        button: document.getElementById("supporterSubmitBtn"),
        message: document.getElementById("supporterMessage"),
    };
}

function setMessage(elements, text, tone = "info") {
    if (!elements.message) return;
    elements.message.textContent = text;
    elements.message.classList.remove("hidden", "is-error", "is-success");
    if (tone === "error") {
        elements.message.classList.add("is-error");
        return;
    }
    if (tone === "success") {
        elements.message.classList.add("is-success");
    }
}

function clearMessage(elements) {
    if (!elements.message) return;
    elements.message.textContent = "";
    elements.message.classList.add("hidden");
    elements.message.classList.remove("is-error", "is-success");
}

function setLoading(elements, loading) {
    if (!elements.button) return;
    elements.button.disabled = loading;
    elements.button.innerHTML = loading
        ? '<i class="fas fa-spinner fa-spin"></i><span>Reindirizzamento...</span>'
        : '<i class="fas fa-mug-hot"></i><span>Buy me a Coffee</span>';
}

function showPrompt(elements) {
    elements.prompt?.classList.remove("hidden");
    elements.thankYou?.classList.add("hidden");
}

function showThankYou(elements, donationCount = 1) {
    elements.prompt?.classList.add("hidden");
    elements.thankYou?.classList.remove("hidden");
    if (!elements.thankYouText) return;
    elements.thankYouText.textContent = donationCount > 1
        ? "Bentornato: il tuo supporto continua a fare la differenza."
        : "Il tuo supporto è stato registrato in questo browser.";
}

async function restoreSupporterState(elements) {
    const supporterToken = getSupporterToken();
    if (!supporterToken) {
        showPrompt(elements);
        return;
    }

    try {
        const status = await getSupporterStatus(supporterToken);
        if (!status.recognized) {
            clearSupporterToken();
            showPrompt(elements);
            return;
        }
        showThankYou(elements, status.donation_count || 1);
    } catch {
        showPrompt(elements);
        setMessage(elements, "Non riesco a verificare ora lo stato del supporto, ma puoi riprovare tra poco.", "error");
    }
}

async function consumeStripeReturn(elements) {
    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get("session_id");

    if (params.get("supporter_canceled") === "1") {
        showPrompt(elements);
        setMessage(elements, "Donazione annullata. Quando vuoi, il caffè resta qui.", "info");
        cleanupSupporterParams();
        return true;
    }

    if (params.get("supporter_success") !== "1" || !sessionId) {
        return false;
    }

    try {
        setLoading(elements, true);
        clearMessage(elements);
        const result = await confirmSupporterSession(sessionId);
        if (result.token) {
            setSupporterToken(result.token);
        }
        showThankYou(elements, result.donation_count || 1);
    } catch (error) {
        clearSupporterToken();
        showPrompt(elements);
        setMessage(elements, error.message || "La donazione risulta avviata, ma non sono riuscito a confermarla.", "error");
    } finally {
        setLoading(elements, false);
        cleanupSupporterParams();
    }

    return true;
}

export function initializeSupporterWidget() {
    const elements = getElements();
    if (!elements.form || !elements.email || !elements.button) return;

    elements.form.addEventListener("submit", async event => {
        event.preventDefault();
        clearMessage(elements);

        if (!elements.email.reportValidity()) {
            return;
        }

        try {
            setLoading(elements, true);
            const result = await createSupporterCheckoutSession(elements.email.value.trim());
            window.location.href = result.checkout_url;
        } catch (error) {
            setMessage(elements, error.message || "Non sono riuscito ad avviare la donazione.", "error");
            setLoading(elements, false);
        }
    });

    showPrompt(elements);

    consumeStripeReturn(elements)
        .then(consumed => {
            if (!consumed) {
                return restoreSupporterState(elements);
            }
            return null;
        })
        .finally(() => {
            setLoading(elements, false);
        });
}
