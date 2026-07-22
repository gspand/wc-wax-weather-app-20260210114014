/* Bikepacking Diary – minimal service worker for offline app shell */

const CACHE = "bikepacking-v1";
const SHELL = ["/", "/static/css/app.css"];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
        ).then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    if (event.request.method !== "GET") return;
    const url = new URL(event.request.url);
    if (url.origin !== self.location.origin) return;
    event.respondWith(
        caches.open(CACHE).then((cache) => {
            return cache.match(event.request).then((cached) => {
                const network = fetch(event.request).then((response) => {
                    if (response && response.ok) {
                        cache.put(event.request, response.clone());
                    }
                    return response;
                });
                // Stale-while-revalidate: return cached immediately, update in background
                return cached ? (network.catch(() => {}), cached) : network;
            });
        })
    );
});
