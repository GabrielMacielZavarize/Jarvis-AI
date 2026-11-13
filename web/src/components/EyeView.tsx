import { type FormEvent, useEffect, useRef, useState } from 'react';
import { deviceTitle, learningMinutes, useNetworkDevices } from '../lib/network';
import { checkPassword, guessKind, kindLabel, looksPersonal, OSINT_KINDS, useOsint } from '../lib/osint';
import type { NetworkDevice, OsintKind, ServerStatus } from '../lib/types';
import { Panel } from './Panel';
import { Workspace } from './Workspace';
import { OsintBody } from './cards/OsintCard';

const numberFormat = new Intl.NumberFormat('pt-BR');

/** Senha em vazamentos: o SHA-1 é calculado aqui e só os 5 primeiros caracteres saem do navegador. */
function PasswordCheck({ disabled }: { disabled: boolean }) {
  const [password, setPassword] = useState('');
  const [state, setState] = useState<{ status: 'idle' | 'busy' | 'done' | 'error'; count?: number; message?: string }>({ status: 'idle' });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!password || state.status === 'busy') return;
    setState({ status: 'busy' });
    try {
      const count = await checkPassword(password);
      setState({ status: 'done', count });
    } catch (error) {
      setState({ status: 'error', message: error instanceof Error ? error.message : 'A consulta falhou.' });
    }
    // A senha não fica no campo nem na memória da página depois da consulta.
    setPassword('');
  };

  return (
    <Panel code="ODD-42" title="Senha vazada?" className="eye__extra">
      <form className="eye__form" onSubmit={submit}>
        <input
          type="password"
          className="eye__input"
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
            if (state.status !== 'idle') setState({ status: 'idle' });
          }}
          placeholder="Digite uma senha para conferir"
          aria-label="Senha para conferir em vazamentos"
          autoComplete="off"
          maxLength={200}
          disabled={disabled}
        />
        <button type="submit" className="btn eye__go" disabled={disabled || !password || state.status === 'busy'}>
          {state.status === 'busy' ? 'Conferindo…' : 'Conferir'}
        </button>
      </form>
      <div aria-live="polite">
        {state.status === 'done' && state.count === 0 && (
          <div className="osint__verdict osint__verdict--ok">
            <b aria-hidden>✓</b> Não aparece em vazamentos conhecidos
          </div>
        )}
        {state.status === 'done' && (state.count ?? 0) > 0 && (
          <div className="osint__verdict osint__verdict--danger">
            <b aria-hidden>✕</b> Apareceu {numberFormat.format(state.count ?? 0)} {state.count === 1 ? 'vez' : 'vezes'} em vazamentos: não use
          </div>
        )}
        {state.status === 'error' && (
          <div className="notice" role="alert">
            {state.message}
          </div>
        )}
      </div>
      <p className="osint__note">
        A senha não sai deste navegador: ele calcula o código dela (SHA-1) e pede ao serviço só os 5 primeiros caracteres, que milhares de
        senhas diferentes têm em comum.
      </p>
    </Panel>
  );
}

/** Um aparelho da lista: nome editável, "conhecido" e esquecer. */
function DeviceRow({ device, busy }: { device: NetworkDevice; busy: boolean }) {
  const { rename, setKnown, forget } = useNetworkDevices();
  const [name, setName] = useState(device.name);
  useEffect(() => setName(device.name), [device.name]);
  const save = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim() !== device.name) void rename(device.mac, name.trim());
  };
  return (
    <li className={`devices__row ${device.known ? '' : 'devices__row--new'}`}>
      <div className="devices__id">
        <b>{deviceTitle(device)}</b>
        {!device.known && <span className="devices__tag devices__tag--new">novo</span>}
        {device.private && (
          <span className="devices__tag" title="MAC aleatório: celulares e notebooks modernos usam um por rede e alguns trocam de tempos em tempos">
            endereço privado
          </span>
        )}
        <code>
          {device.ip || 'sem IP'} · {device.mac}
        </code>
      </div>
      <form className="devices__edit" onSubmit={save}>
        <input
          className="eye__input devices__name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Dar um nome"
          aria-label={`Nome do aparelho ${device.ip || device.mac}`}
          maxLength={40}
          autoComplete="off"
        />
        <button type="submit" className="chip-btn" disabled={busy || name.trim() === device.name}>
          Salvar
        </button>
        {!device.known && (
          <button type="button" className="chip-btn" disabled={busy} onClick={() => void setKnown(device.mac, true)}>
            É meu
          </button>
        )}
        <button
          type="button"
          className="chip-btn"
          disabled={busy}
          title="Tira da lista. Se ele aparecer de novo, o Jarvis avisa como aparelho novo."
          onClick={() => void forget(device.mac)}
        >
          Esquecer
        </button>
      </form>
    </li>
  );
}

/** Aparelhos que o PC viu no Wi-Fi (JARVIS_NETWORK_WATCH): dar nome ou marcar como conhecido. */
function NetworkDevices() {
  const { data, error, busy, load } = useNetworkDevices();
  useEffect(() => {
    void load();
  }, [load]);
  const left = learningMinutes(data?.learning_until ?? null);
  return (
    <Panel code="ODD-42" title="Aparelhos na rede" className="eye__extra" extra={data ? <span>{data.devices.length}</span> : undefined}>
      {error && (
        <div className="notice" role="alert">
          <strong>Não deu.</strong> {error}
        </div>
      )}
      {data && !data.watching && (
        <div className="notice">
          O aviso de aparelho novo está desligado. Ponha <code>JARVIS_NETWORK_WATCH=true</code> (e <code>JARVIS_PROACTIVE=true</code>) no <code>.env</code>.
        </div>
      )}
      {data?.learning && (
        <p className="osint__note" role="status">
          Aprendendo a rede em silêncio{left ? `: faltam uns ${left} min` : ''}. Quem aparecer agora entra como conhecido, sem aviso.
        </p>
      )}
      {data && data.devices.length === 0 ? (
        <p className="stage__empty-text">Nenhum aparelho guardado ainda. Eles aparecem depois da primeira leitura da tabela ARP (a cada 5 minutos).</p>
      ) : (
        <ul className="devices">{data?.devices.map((device) => <DeviceRow key={device.mac} device={device} busy={busy} />)}</ul>
      )}
      {data && data.unreviewed > 0 && (
        <p className="osint__note">
          {data.unreviewed} {data.unreviewed === 1 ? 'aparelho novo ainda não foi revisado' : 'aparelhos novos ainda não foram revisados'}: dê um nome a ele ou marque como seu.
        </p>
      )}
    </Panel>
  );
}

/**
 * Olho de Deus (ODD-42): consultas em fontes públicas. Um campo só reconhece o que foi digitado
 * (IP, domínio, link, CNPJ, CEP, DDD, email ou usuário) e os resultados ficam empilhados ao lado.
 */
export function EyeView({ server }: { server: ServerStatus | null }) {
  const { results, pending, error, run, remove, clear } = useOsint();
  const [text, setText] = useState('');
  const [picked, setPicked] = useState<OsintKind | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const enabled = server?.osint?.enabled ?? false;
  const network = server?.osint?.network ?? false;
  const guessed = guessKind(text);
  const kind = picked ?? guessed;
  const personal = !picked && looksPersonal(text);

  useEffect(() => input.current?.focus(), []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!text.trim() || pending || !enabled) return;
    void run(text.trim(), picked);
  };

  const pick = (id: OsintKind) => {
    if (id === 'network') {
      if (network && !pending) void run('', 'network');
      return;
    }
    setPicked((current) => (current === id ? null : id));
    input.current?.focus();
  };

  return (
    <Workspace view="eye">
      <div className="workspace__col">
        <Panel code="ODD-42" title="Consulta" extra={kind && text.trim() ? <span>{kindLabel(kind)}</span> : undefined}>
          {!server ? (
            <div className="notice">
              <strong>Servidor offline.</strong> As consultas passam pelo servidor do Jarvis: rode <code>python jarvis.py</code>.
            </div>
          ) : !enabled ? (
            <div className="notice">
              <strong>Olho de Deus desligado.</strong> Tire o <code>JARVIS_ENABLE_OSINT=false</code> do <code>.env</code> para ligar.
            </div>
          ) : null}
          <form className="eye__form" onSubmit={submit}>
            <input
              ref={input}
              className="eye__input"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="IP, domínio, link, CNPJ, CEP, DDD, email ou usuário"
              aria-label="O que consultar"
              autoComplete="off"
              spellCheck={false}
              maxLength={2000}
              disabled={!enabled}
            />
            <button type="submit" className="btn eye__go" disabled={!enabled || pending || !text.trim() || personal}>
              {pending ? 'Consultando…' : 'Consultar'}
            </button>
          </form>
          <div className="eye__kinds" role="group" aria-label="Tipo de consulta">
            {OSINT_KINDS.map((item) => {
              const off = item.id === 'network' && !network;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`chip-btn ${kind === item.id && item.id !== 'network' ? 'chip-btn--on' : ''}`}
                  aria-pressed={item.id === 'network' ? undefined : picked === item.id}
                  title={off ? 'Vem desligada: JARVIS_OSINT_NETWORK=true no .env' : item.hint}
                  disabled={!enabled || off}
                  onClick={() => pick(item.id)}
                >
                  {item.label}
                </button>
              );
            })}
          </div>
          <p className="eye__hint" aria-live="polite">
            {personal
              ? 'Isso parece um CPF ou telefone. O Olho de Deus só usa fontes públicas e não consulta dados pessoais de terceiros.'
              : picked
                ? `Consultando como ${kindLabel(picked)}. Clique de novo no tipo para voltar ao reconhecimento automático.`
                : text.trim()
                  ? guessed
                    ? `Reconhecido como ${kindLabel(guessed)}.`
                    : 'Não reconheci o formato: escolha o tipo abaixo do campo.'
                  : 'O tipo é reconhecido pelo formato do que você digitar.'}
          </p>
          {error && (
            <div className="notice" role="alert">
              <strong>Não deu.</strong> {error}
            </div>
          )}
        </Panel>
        <PasswordCheck disabled={!enabled} />
        {enabled && network && <NetworkDevices />}
        <Panel code="ODD-42" title="O que ele consulta" className="eye__extra">
          <ul className="eye__about">
            {OSINT_KINDS.map((item) => (
              <li key={item.id}>
                <b>{item.label}</b>
                <span>{item.hint}</span>
              </li>
            ))}
          </ul>
          <p className="osint__note">
            Só fontes públicas e legais. CPF, telefone, endereço de pessoas e bases vazadas ficam de fora, de propósito. Por voz: “Jarvis, de onde
            é o IP 8.8.8.8?”, “esse link é golpe?”.
          </p>
        </Panel>
      </div>

      <div className="workspace__col workspace__col--wide">
        {results.length === 0 ? (
          <Panel code="ODD-42" title="Resultados">
            <p className="stage__empty-text">
              Os resultados aparecem aqui, o mais recente em cima, e somem quando a aba fecha. O que tiver lugar conhecido (um IP, o servidor de um
              domínio) também ganha um arco no globo do Painel.
            </p>
          </Panel>
        ) : (
          <>
            <div className="eye__bar">
              <span>
                {results.length} {results.length === 1 ? 'resultado' : 'resultados'} nesta sessão
              </span>
              <button type="button" className="chip-btn" onClick={clear}>
                Limpar
              </button>
            </div>
            {results.map((result) => (
              <Panel
                key={`${result.kind}:${result.target}`}
                code="ODD-42"
                title={result.label}
                extra={
                  <>
                    <span>{new Date(result.ts * 1000).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}</span>
                    <button type="button" className="icon-btn" aria-label={`Fechar ${result.title}`} onClick={() => remove(result.ts)}>
                      <svg width="10" height="10" viewBox="0 0 10 10" stroke="currentColor" strokeWidth="1.5" aria-hidden>
                        <path d="M1 1l8 8M9 1L1 9" />
                      </svg>
                    </button>
                  </>
                }
              >
                <OsintBody data={result} />
              </Panel>
            ))}
          </>
        )}
      </div>
    </Workspace>
  );
}
