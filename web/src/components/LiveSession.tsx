import { RoomAudioRenderer, SessionProvider, StartAudio, useSession } from '@livekit/components-react';
import { ConnectionState, TokenSource } from 'livekit-client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useLiveJarvis } from '../hooks/useLiveJarvis';
import type { LiveJarvis } from '../hooks/liveState';

const newRoomName = () => `jarvis-${crypto.randomUUID().slice(0, 8)}`;

/**
 * Dono da sessão do LiveKit. Fica num pedaço à parte do pacote (o App o carrega com `lazy`) e só
 * é montado quando o servidor pode emitir tokens: sem LiveKit configurado, o navegador nem baixa o código.
 */
export default function LiveSession({ onChange }: { onChange: (live: LiveJarvis) => void }) {
  const tokenSource = useMemo(() => TokenSource.endpoint('/api/token'), []);
  // A fresh room per session guarantees the agent is dispatched again on reconnect
  // (agent dispatch only happens when LiveKit creates the room).
  const [roomName, setRoomName] = useState(newRoomName);
  const session = useSession(tokenSource, { agentName: 'jarvis', participantName: 'Operador', roomName });
  const wasConnected = useRef(false);

  useEffect(() => {
    if (session.connectionState === ConnectionState.Connected) {
      wasConnected.current = true;
    } else if (session.connectionState === ConnectionState.Disconnected && wasConnected.current) {
      wasConnected.current = false;
      setRoomName(newRoomName());
    }
  }, [session.connectionState]);

  return (
    <SessionProvider session={session}>
      <LiveBridge onChange={onChange} />
      <RoomAudioRenderer />
      {/* Only shows when the browser blocks the voice, e.g. a tab opened by "Jarvis" without a click yet. */}
      <StartAudio label="Clique para ouvir o Jarvis" className="btn btn--primary start-audio" />
    </SessionProvider>
  );
}

function LiveBridge({ onChange }: { onChange: (live: LiveJarvis) => void }) {
  const live = useLiveJarvis();
  useEffect(() => onChange(live), [live, onChange]);
  return null;
}
