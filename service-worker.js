/* eslint-disable no-restricted-globals */

const CACHE_NAME = "alpenwetter-v28";
const RUNTIME_CACHE = "alpenwetter-runtime-v19";

const APP_SHELL = [
    "./",
    "./index.html",
    "./manifest.webmanifest",
    "./icons/icon-192.png",
    "./icons/icon-512.png",
    "./icons/apple-touch-icon.png",
];

const OPTIONAL_SHELL = [
    "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
    "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
    "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
    "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
    "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
    "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js",
];

const API_HOSTS = new Set([
    "api.open-meteo.com",
    "geocoding-api.open-meteo.com",
    "dataset.api.hub.geosphere.at",
    "warnungen.zamg.at",
    "static.avalanche.report",
]);

const isAppShellRequest = (url) => {
    if (url.origin !== self.location.origin) return false;
    const path = url.pathname || "";
    if (path.endsWith("/") || path.endsWith("/index.html")) return true;
    if (path.endsWith("/manifest.webmanifest")) return true;
    if (path.endsWith("/service-worker.js")) return true;
    if (path.includes("/icons/")) return true;
    return false;
};

const cacheFirst = async (request, cacheName) => {
    const cache = await caches.open(cacheName);
    const cached = await cache.match(request, { ignoreSearch: true });
    if (cached) return cached;
    const response = await fetch(request);
    if (response && (response.ok || response.type === "opaque")) {
        cache.put(request, response.clone());
    }
    return response;
};

const staleWhileRevalidate = async (request, cacheName) => {
    const cache = await caches.open(cacheName);
    const cached = await cache.match(request, { ignoreSearch: true });

    const fetchPromise = fetch(request)
        .then((response) => {
            if (response && (response.ok || response.type === "opaque")) {
                cache.put(request, response.clone());
            }
            return response;
        })
        .catch(() => null);

    if (cached) return cached;
    const response = await fetchPromise;
    return response || cached;
};

const networkFirst = async (request, cacheName) => {
    const cache = await caches.open(cacheName);
    try {
        const response = await fetch(request);
        if (response && (response.ok || response.type === "opaque")) {
            cache.put(request, response.clone());
        }
        return response;
    } catch (err) {
        const cached = await cache.match(request, { ignoreSearch: true });
        if (cached) return cached;
        throw err;
    }
};

self.addEventListener("install", (event) => {
    event.waitUntil(
        (async () => {
            const cache = await caches.open(CACHE_NAME);
            await cache.addAll(APP_SHELL);
            await Promise.allSettled(
                OPTIONAL_SHELL.map(async (url) => {
                    try {
                        await cache.add(url);
                    } catch {
                        // optional
                    }
                })
            );
            self.skipWaiting();
        })()
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        (async () => {
            const keys = await caches.keys();
            await Promise.all(keys.map((key) => (key === CACHE_NAME || key === RUNTIME_CACHE ? null : caches.delete(key))));
            self.clients.claim();
        })()
    );
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    if (!request || request.method !== "GET") return;

    const url = new URL(request.url);

    // Navigations: serve app shell for fast startups (and offline).
    if (request.mode === "navigate") {
        event.respondWith(staleWhileRevalidate("./index.html", CACHE_NAME));
        return;
    }

    // App shell assets: cache-first.
    if (isAppShellRequest(url)) {
        event.respondWith(staleWhileRevalidate(request, CACHE_NAME));
        return;
    }

    // Don't cache map tiles (potentially unbounded and provider-side transient failures).
    if (url.hostname.endsWith("tile.openstreetmap.org") || url.hostname.endsWith("basemaps.cartocdn.com")) {
        return;
    }

    // API calls: network-first with cache fallback.
    if (API_HOSTS.has(url.hostname)) {
        event.respondWith(networkFirst(request, RUNTIME_CACHE));
        return;
    }

    // Static CDN assets: cache-first for faster cold starts.
    if (
        url.hostname.endsWith("unpkg.com") ||
        url.hostname.endsWith("jsdelivr.net") ||
        url.hostname.endsWith("fonts.googleapis.com") ||
        url.hostname.endsWith("fonts.gstatic.com")
    ) {
        event.respondWith(cacheFirst(request, RUNTIME_CACHE));
    }
});
