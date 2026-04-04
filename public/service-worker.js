const CACHE_NAME = "meteo-ai-static-v7";
const STATIC_ASSETS = [
    "/",
    "/index.html",
    "/style.css",
    "/manifest.webmanifest",
    "/js/main.js",
    "/js/api.js",
    "/js/config.js",
    "/js/render.js",
    "/js/autocomplete.js",
    "/js/storage.js",
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
