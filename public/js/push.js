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

    // Controlla se già iscritto
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
            // Ottieni VAPID public key dal backend
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
            // Registra sul backend
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
