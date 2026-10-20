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
import './styles/cards.css';
import './styles/boot.css';
import './styles/mobile.css';
import './styles/personas.css';

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { registerServiceWorker } from './lib/pwa';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

registerServiceWorker();
