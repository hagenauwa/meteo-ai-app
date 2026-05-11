const BACKEND_URL = window.BACKEND_URL || "http://localhost:8000";

function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
}

export async function initializePush() {
    const btn = document.getElementById("pushToggle");
    const icon = document.getElementById("pushIcon");
    if (!btn || !icon) return;
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        btn.style.display = "none";
        return;
    }

    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    updateIcon(icon, !!sub);

    btn.addEventListener("click", async () => {
        const reg = await navigator.serviceWorker.ready;
        const existing = await reg.pushManager.getSubscription();
        if (existing) {
            await existing.unsubscribe();
            updateIcon(icon, false);
            return;
        }
        try {
            const keyRes = await fetch(`${BACKEND_URL}/api/subscriptions/vapid-public-key`).catch(() => null);
            let vapidKey = null;
            if (keyRes && keyRes.ok) {
                const data = await keyRes.json();
                vapidKey = data.publicKey;
            }
            if (!vapidKey) {
                alert("Le notifiche push non sono ancora configurate.");
                return;
            }
            const newSub = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(vapidKey),
            });
            await fetch(`${BACKEND_URL}/api/subscriptions/register`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    subscription: {
                        endpoint: newSub.endpoint,
                        keys: {
                            p256dh: newSub.getKey('p256dh'),
                            auth: newSub.getKey('auth'),
                        },
                    },
                    city: window.currentCity?.name || null,
                }),
            });
            updateIcon(icon, true);
        } catch (err) {
            console.error("Push subscription failed:", err);
            alert("Impossibile attivare le notifiche. Verifica le autorizzazioni del browser.");
        }
    });
}

function updateIcon(icon, active) {
    icon.className = active ? "fas fa-bell" : "fas fa-bell-slash";
    icon.parentElement.title = active ? "Disattiva notifiche" : "Attiva notifiche meteo";
}

export async function toggleRainAlert(enabled, cityName) {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (!sub) {
        alert("Attiva prima le notifiche push per ricevere le allerte pioggia.");
        return false;
    }

    try {
        const response = await fetch(`${BACKEND_URL}/api/subscriptions/rain-alerts`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                endpoint: sub.endpoint,
                enabled: enabled,
                city: cityName || window.currentCity?.name || null,
            }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || "Errore del server");
        }

        const data = await response.json();
        return data.success;
    } catch (err) {
        console.error("Rain alert toggle failed:", err);
        alert(`Impossibile ${enabled ? 'attivare' : 'disattivare'} le allerte pioggia: ${err.message}`);
        return false;
    }
}

export async function getRainAlertStatus() {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (!sub) {
        return { rain_alerts_enabled: false, city: null, last_rain_alert_at: null };
    }

    try {
        const params = new URLSearchParams({ endpoint: sub.endpoint });
        const response = await fetch(`${BACKEND_URL}/api/subscriptions/rain-alerts?${params.toString()}`);
        if (!response.ok) return { rain_alerts_enabled: false, city: null, last_rain_alert_at: null };
        return await response.json();
    } catch {
        return { rain_alerts_enabled: false, city: null, last_rain_alert_at: null };
    }
}
