import '@fontsource/orbitron/latin-500.css';
import '@fontsource/orbitron/latin-700.css';
import '@fontsource/rajdhani/latin-400.css';
import '@fontsource/rajdhani/latin-500.css';
import '@fontsource/rajdhani/latin-600.css';
import '@fontsource/share-tech-mono/latin-400.css';
import './styles/global.css';
import './styles/hud.css';
import './styles/cards.css';
import './styles/boot.css';
import './styles/mobile.css';

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
