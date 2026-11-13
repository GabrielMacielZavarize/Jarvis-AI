import { useHud } from './hudStore';
import { useOsint } from './osint';

/** Para a paleta de comandos: abre o Olho de Deus e já consulta (sem puxar a área inteira junto). */
export function openEyeWith(target: string) {
  useHud.getState().setView('eye');
  void useOsint.getState().run(target, null);
}
