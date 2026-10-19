import { type FormEvent, useEffect, useRef, useState } from 'react';
import { CODE_DIGITS, deviceNameGuess, normalizeCode, pairCodeFromHash, pairDevice } from '../lib/lan';

interface PairingScreenProps {
  revoked: boolean;
  onPaired: () => void;
}

/** LAN-26: what an unpaired phone sees. The code (or the QR link) comes from the PC's HUD. */
export function PairingScreen({ revoked, onPaired }: PairingScreenProps) {
  const [code, setCode] = useState('');
  const [name, setName] = useState(() => deviceNameGuess(navigator.userAgent));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const triedHash = useRef<string | null>(null);

  const submit = async (value: string) => {
    if (busy || value.length !== CODE_DIGITS) return;
    setBusy(true);
    setError(null);
    try {
      await pairDevice(value, name);
      onPaired();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Não foi possível parear.');
    } finally {
      setBusy(false);
    }
  };

  // The QR opens https://ip:8000/#parear=123456: pair right away and drop the code from the URL.
  // hashchange covers a QR read while this screen is already open.
  useEffect(() => {
    const fromHash = () => {
      const fromLink = pairCodeFromHash(window.location.hash);
      if (!fromLink || triedHash.current === fromLink) return;
      triedHash.current = fromLink;
      history.replaceState(null, '', window.location.pathname);
      setCode(fromLink);
      void submit(fromLink);
    };
    fromHash();
    window.addEventListener('hashchange', fromHash);
    return () => window.removeEventListener('hashchange', fromHash);
  }, []);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void submit(code);
  };

  return (
    <main className="pairing">
      <form className="pairing__card panel" onSubmit={onSubmit}>
        <header className="panel__head">
          <span className="panel__code">LAN-26</span>
          <h1 className="panel__title">Parear este aparelho</h1>
        </header>
        <div className="panel__body pairing__body">
          <p className="pairing__brand">J.A.R.V.I.S.</p>
          {revoked && (
            <p className="pairing__alert" role="alert">
              Este aparelho foi revogado no PC. Pareie de novo para continuar.
            </p>
          )}
          <p className="pairing__hint">
            No PC, abra o painel <strong>Celular</strong> do HUD e toque em <strong>Parear celular</strong>. Digite o código
            de 6 dígitos ou leia o QR com a câmera.
          </p>
          <label className="pairing__label" htmlFor="pair-code">
            Código
          </label>
          <input
            id="pair-code"
            className="pairing__code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]*"
            placeholder="000000"
            value={code}
            onChange={(event) => setCode(normalizeCode(event.target.value))}
            autoFocus
          />
          <label className="pairing__label" htmlFor="pair-name">
            Nome do aparelho
          </label>
          <input
            id="pair-name"
            className="pairing__name"
            maxLength={40}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          {error && (
            <p className="pairing__alert" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="btn btn--primary pairing__submit" disabled={busy || code.length !== CODE_DIGITS}>
            {busy ? 'Pareando…' : 'Parear'}
          </button>
          <p className="pairing__foot">
            Aviso de certificado? Instale o <a href="/api/lan/ca.crt">certificado do Jarvis</a> (passo a passo em docs/celular.md).
          </p>
        </div>
      </form>
    </main>
  );
}
