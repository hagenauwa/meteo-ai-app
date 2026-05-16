const CACHE_NAME = "le-previsioni-static-v19-ml-impact";
const STATIC_ASSETS = [
    "/",
    "/index.html",
    "/style.css",
    "/manifest.webmanifest",
    "/js/main.js",
    "/js/telegram.js",
    "/js/api.js",
    "/js/config.js",
    "/js/render.js",
    "/js/autocomplete.js",
    "/js/storage.js",
    "/js/supporter.js",
    "/icons/apple-touch-icon.png",
    "/icons/favicon-32.png",
    "/icons/icon-192.png",
    "/icons/icon-512.png",
];

async function updateCache(request, response) {
    if (!response || response.status !== 200 || response.type !== "basic") {
        return response;
    }

    const cache = await caches.open(CACHE_NAME);
    await cache.put(request, response.clone());
    return response;
}

async function networkFirst(request) {
    try {
        const response = await fetch(new Request(request, { cache: "no-store" }));
        return updateCache(request, response);
    } catch (error) {
        const cached = await caches.match(request);
        if (cached) return cached;
        throw error;
    }
}

self.addEventListener("install", event => {
    event.waitUntil(
        caches
            .open(CACHE_NAME)
            .then(cache => cache.addAll(STATIC_ASSETS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("push", (event) => {
    const data = event.data?.json() || {};
    const title = data.title || "Le Previsioni";
    const body = data.body || "Aggiornamento meteo disponibile";
    const icon = data.icon || "./assets/icons/icon-192x192.png";
    const badge = data.badge || "./assets/icons/icon-72x72.png";
    const isRainAlert = data.data?.type === "rain_alert";

    event.waitUntil(
        self.registration.showNotification(title, {
            body,
            icon,
            badge,
            tag: data.tag || (isRainAlert ? "rain-alert" : "meteo-update"),
            requireInteraction: isRainAlert ? true : false,
            data: data.data || {},
        })
    );
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const city = event.notification.data?.city;
    const url = city ? `/?city=${encodeURIComponent(city)}` : "/";

    event.waitUntil(
        clients.matchAll({ type: "window", includeUncontrolled: true }).then(clientList => {
            for (const client of clientList) {
                if (client.url.includes("leprevisioni.netlify.app") || client.url.includes("localhost")) {
                    return client.focus();
                }
            }
            return clients.openWindow(url);
        })
    );
});

self.addEventListener("activate", event => {
    event.waitUntil(
        caches
            .keys()
            .then(keys =>
                Promise.all(
                    keys
                        .filter(key => key !== CACHE_NAME)
                        .map(key => caches.delete(key))
                )
            )
            .then(() => self.clients.claim())
    );
});

self.addEventListener("message", event => {
    if (event.data?.type === "SKIP_WAITING") {
        self.skipWaiting();
    }
});

self.addEventListener("fetch", event => {
    if (event.request.method !== "GET") return;

    const url = new URL(event.request.url);
    if (url.origin !== self.location.origin) return;

    const isNavigationRequest = event.request.mode === "navigate";
    const isStaticAsset = STATIC_ASSETS.includes(url.pathname);
    if (!isNavigationRequest && !isStaticAsset) return;

    event.respondWith(networkFirst(event.request));
});
