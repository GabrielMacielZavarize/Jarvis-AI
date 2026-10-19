/** LAN-26: the service worker makes the HUD installable on the phone (Chrome/Android). It only
 * answers page navigations, offline; the API, the camera feed and LiveKit always go to the network. */
export function shouldRegisterServiceWorker(env: { secure: boolean; supported: boolean; dev: boolean }): boolean {
  return env.supported && env.secure && !env.dev;
}

export function registerServiceWorker(): void {
  const supported = typeof navigator !== 'undefined' && 'serviceWorker' in navigator;
  if (!shouldRegisterServiceWorker({ supported, secure: window.isSecureContext, dev: import.meta.env.DEV })) return;
  window.addEventListener('load', () => {
    // An untrusted certificate (CA not installed yet) refuses the worker: the HUD works anyway.
    navigator.serviceWorker.register('/sw.js').catch(() => undefined);
  });
}
