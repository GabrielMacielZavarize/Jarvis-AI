// LAN-26: service worker do HUD do Jarvis. Só existe para o PWA ser instalável e mostrar um aviso
// quando o PC não responde; nada é guardado em cache (o HUD sempre vem novo do servidor).
const OFFLINE = `<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>J.A.R.V.I.S.</title>
<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#02060b;color:#5ff4ff;font-family:monospace;text-align:center;padding:24px">
<div><h1 style="letter-spacing:.3em">J.A.R.V.I.S.</h1>
<p>O PC não respondeu.</p><p style="color:#9cc">Confira se o Jarvis está rodando com <b>--lan</b> e se o celular está no Wi-Fi de casa.</p>
<button onclick="location.reload()" style="margin-top:12px;padding:14px 28px;background:transparent;color:#5ff4ff;border:1px solid #5ff4ff;font:inherit">Tentar de novo</button></div></body></html>`;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (event) => {
  if (event.request.mode !== 'navigate') return;
  event.respondWith(
    fetch(event.request).catch(
      () => new Response(OFFLINE, { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }),
    ),
  );
});
