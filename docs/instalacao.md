# Instalação e configuração

## O que precisa

- Python 3.10 ou mais novo.
- Node.js 20 ou mais novo, para compilar o HUD.
- Conta no [LiveKit Cloud](https://cloud.livekit.io). O plano gratuito serve para começar.
- Uma chave de modelo: `GOOGLE_API_KEY` para o Gemini Live (padrão) ou `OPENAI_API_KEY` para os backends da OpenAI.
- PortAudio, só se for usar o modo `console` no terminal.

## Instalando

No Windows (PowerShell):

```powershell
git clone https://github.com/GabrielMacielZavarize/Jarvis-AI.git
cd Jarvis-AI
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
```

No Linux ou macOS:

```bash
git clone https://github.com/GabrielMacielZavarize/Jarvis-AI.git
cd Jarvis-AI
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Preencha o `.env` (próximas seções) e baixe os modelos locais que o LiveKit usa:

```bash
python agent.py download-files
```

O `.env.example` tem todas as variáveis comentadas. Aqui ficam só as do núcleo; cada recurso opcional explica as suas na própria página.

## LiveKit

Obrigatório para conversar por voz. Crie um projeto no LiveKit Cloud e copie as credenciais em Settings > Keys:

```env
LIVEKIT_URL=wss://seu-projeto.livekit.cloud
LIVEKIT_API_KEY=sua-api-key
LIVEKIT_API_SECRET=seu-api-secret
```

## Backend de voz

### Gemini Live (padrão)

O modelo padrão é o `gemini-3.8-live`, o Live estável que o Google recomenda para agentes de voz. Ele está no plano gratuito da Gemini API.

Para gerar a chave:

1. Entre no [Google AI Studio](https://aistudio.google.com/apikey) com a sua conta Google.
2. Clique em Create API key e escolha (ou crie) um projeto. Não pede cartão.
3. Cole a chave em `GOOGLE_API_KEY`.

```env
JARVIS_BACKEND=gemini-realtime
GOOGLE_API_KEY=sua-chave-google
GOOGLE_MODEL=gemini-3.8-live
JARVIS_VOICE=Charon
```

`JARVIS_VOICE` escolhe a voz (veja [voz.md](voz.md#voz-e-persona)). O nome antigo, `GOOGLE_VOICE`, ainda funciona.

No plano gratuito o Google pode usar o conteúdo das conversas para melhorar os produtos dele, e os limites valem por modelo (estão em AI Studio > Rate limits). Também funcionam como `GOOGLE_MODEL`: `gemini-3.1-flash-live-preview`, `gemini-3.8-live-extended-thinking` (pensa mais e responde mais devagar) e `gemini-2.5-flash-native-audio-preview-12-2025` (geração anterior).

Modelos de reserva, rodízio e tempo de resposta estão em [modelos.md](modelos.md).

### OpenAI Realtime

```env
JARVIS_BACKEND=openai-realtime
OPENAI_API_KEY=sua-chave-openai
OPENAI_REALTIME_MODEL=gpt-realtime
OPENAI_VOICE=marin
```

### Provider compatível com OpenAI

Esse modo usa transcrição, LLM e fala separados (`pipeline-first`) e funciona no melhor esforço. O endpoint precisa ter os paths de chat, STT e TTS.

```env
JARVIS_BACKEND=openai-compatible-pipeline
OPENAI_API_KEY=sua-chave
OPENAI_BASE_URL=https://seu-endpoint/v1
OPENAI_LLM_MODEL=gpt-4.1
OPENAI_STT_MODEL=gpt-4o-mini-transcribe
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=ash
```

## Controle do computador e cidade

```env
JARVIS_ENABLE_PC_CONTROL=true
JARVIS_HOME_CITY=Criciúma
```

`JARVIS_ENABLE_PC_CONTROL` libera os protocolos que mexem no PC: apps, sites, abas, janelas, mídia, volume e tela. Detalhes em [computador.md](computador.md).

`JARVIS_HOME_CITY` é a cidade usada quando você pede clima ou horário sem dizer onde, e o ponto de partida dos arcos no globo do HUD. Sem ela, o HUD estima uma cidade pelo fuso do navegador. Os destinos dos arcos são aproximados (sede ou região de datacenter conhecida, ou o país do domínio). É uma visualização, não um traceroute.

## Rodando

### Tudo de uma vez

```bash
python jarvis.py
```

Compila o HUD na primeira execução, sobe o worker do agente (`agent.py dev`) e o servidor em `http://127.0.0.1:8000` e abre o navegador. Clique no núcleo (ou aperte Espaço) e fale normalmente.

| Comando | O que faz |
| --- | --- |
| `python jarvis.py --no-agent` | Só o HUD, bom para o modo simulação |
| `python jarvis.py --agent-mode start` | Worker sem hot reload |
| `python jarvis.py --port 8080 --no-browser` | Outra porta, sem abrir o navegador |
| `python jarvis.py --rebuild` | Recompila o HUD |
| `python jarvis.py --lan` | Atende também o celular na rede de casa, com HTTPS e pareamento ([celular.md](celular.md)) |
| `python jarvis.py --gestures` | Liga também os gestos das mãos ([gestos.md](gestos.md)) |
| `pythonw jarvis.py --tray` | Só o ícone na bandeja do Windows, sem console e com os logs em `logs/jarvis.log` ([bandeja.md](bandeja.md)) |
| `python gestures.py --preview` | Só os gestos, com a imagem da webcam para testar |
| `python gestures.py --calibrate` | Calibra os gestos para a sua mão |

Depois de atualizar o código, rode uma vez com `--rebuild`. Sem isso o navegador continua com o HUD antigo.

### Conferindo a configuração

```bash
python doctor.py
```

Mostra o que está configurado, o que falta no `.env`, a fila de modelos do Gemini e o estado de cada recurso opcional.

### Desenvolvendo o HUD com hot reload

Em três terminais:

```bash
python server.py
```

```bash
python agent.py dev
```

```bash
cd web
npm install
npm run dev
```

Abra `http://localhost:5173`. O Vite encaminha `/api` para o `server.py`.

### Outros modos do agente

```bash
python agent.py console          # voz direto no terminal, sem HUD
python agent.py connect --room minha-sala
python generate_playground_token.py --room jarvis-demo --name Gabriel   # LiveKit Agents Playground
```
