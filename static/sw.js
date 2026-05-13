// Estrategia: network-first para la shell (siempre busca versión nueva).
// Si falla la red, sirve de caché para que la app funcione offline.
// Cualquier cambio en este archivo dispara reinstalación del SW en clientes existentes.

const CACHE = "invoice-ocr-v3";
const SHELL = ["/", "/app.js", "/styles.css", "/manifest.json"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);

  // Llamadas API: siempre red, sin caché
  if (url.pathname.startsWith("/api/")) {
    e.respondWith(fetch(e.request));
    return;
  }

  // Shell: intenta red primero (para tener siempre la última versión),
  // si la red falla → cae a caché. Así no quedas atascado en versión vieja.
  e.respondWith(
    fetch(e.request)
      .then((response) => {
        // Guarda copia en caché para uso offline futuro
        const clone = response.clone();
        caches.open(CACHE).then((c) => c.put(e.request, clone)).catch(() => {});
        return response;
      })
      .catch(() => caches.match(e.request).then((cached) => cached || Response.error()))
  );
});
