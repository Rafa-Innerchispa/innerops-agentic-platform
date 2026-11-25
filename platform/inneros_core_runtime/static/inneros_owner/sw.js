/* PWA shell — notificaciones tipo sistema vía ntfy app en el teléfono */
self.addEventListener("install", (e) => {
  e.waitUntil(self.skipWaiting());
});
self.addEventListener("activate", (e) => {
  e.waitUntil(self.clients.claim());
});