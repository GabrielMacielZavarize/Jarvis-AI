import '@fontsource/orbitron/latin-500.css';
import '@fontsource/orbitron/latin-700.css';
import '@fontsource/rajdhani/latin-400.css';
import '@fontsource/rajdhani/latin-500.css';
import '@fontsource/rajdhani/latin-600.css';
import '@fontsource/share-tech-mono/latin-400.css';
// Persona fonts: Teko for the Mark III tactical HUD, Exo 2 for F.R.I.D.A.Y.
import '@fontsource/teko/latin-500.css';
import '@fontsource/teko/latin-600.css';
import '@fontsource/exo-2/latin-400.css';
import '@fontsource/exo-2/latin-600.css';
import './styles/global.css';
import './styles/hud.css';
import './styles/shell.css';
import './styles/cards.css';
import './styles/boot.css';
import './styles/mobile.css';
import './styles/personas.css';
import './styles/a11y.css';
import './styles/contrast.css';

import { StrictMode } from 'react';
import { LazyMotion } from 'motion/react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { registerServiceWorker } from './lib/pwa';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* As animações do motion chegam à parte; até lá os componentes `m` aparecem no estado inicial. */}
    <LazyMotion features={() => import('./lib/motionFeatures').then((module) => module.default)} strict>
      <App />
    </LazyMotion>
  </StrictMode>,
);

registerServiceWorker();

// Um pedaço que sumiu do servidor (o HUD foi recompilado com a aba aberta) não deve deixar a tela
// em branco: recarrega uma vez para pegar os arquivos novos.
window.addEventListener('vite:preloadError', (event) => {
  event.preventDefault();
  try {
    if (window.sessionStorage.getItem('jarvis.chunk-reload')) return;
    window.sessionStorage.setItem('jarvis.chunk-reload', '1');
  } catch {
    // Sem sessionStorage a recarga pode se repetir, mas só enquanto o pedaço faltar.
  }
  window.location.reload();
});
