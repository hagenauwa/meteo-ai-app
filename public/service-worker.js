const CACHE_NAME = "meteo-ai-static-v2";
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

self.addEventListener("install", event => {
    event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS)));
});

self.addEventListener("activate", event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys
                    .filter(key => key !== CACHE_NAME)
                    .map(key => caches.delete(key))
            )
        )
    );
});

self.addEventListener("fetch", event => {
    if (event.request.method !== "GET") return;
    event.respondWith(
        caches.match(event.request).then(cached => {
            if (cached) return cached;
            return fetch(event.request).then(response => {
                if (!response || response.status !== 200 || response.type !== "basic") {
                    return response;
                }
                const copy = response.clone();
                caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
                return response;
            });
        })
    );
});
