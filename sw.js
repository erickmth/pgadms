const CACHE_NAME = "sistema-escalas-v1";
const FILES_TO_CACHE = [
  "/",
  "/index.html",
  "/offline.html",
  "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css",
  "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css"
];

// Instala o cache
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(FILES_TO_CACHE);
    })
  );
  self.skipWaiting();
});

// Ativa e limpa caches antigos
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.map(key => {
        if (key !== CACHE_NAME) return caches.delete(key);
      }))
    )
  );
  self.clients.claim();
});

// Intercepta todas as requisições
self.addEventListener("fetch", event => {
  event.respondWith(
    fetch(event.request).catch(() => {
      // se for navegação (ex: index.html), manda para offline.html
      if (event.request.mode === "navigate") {
        return caches.match("/offline.html");
      } else {
        return caches.match(event.request);
      }
    })
  );
});
