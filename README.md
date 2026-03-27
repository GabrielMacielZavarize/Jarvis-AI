# Jarvis

Assistente de voz em Python com LiveKit Agents, persona estilo Jarvis, tools úteis e arquitetura pronta para múltiplos providers.

Short English summary: this project is a portfolio-ready voice assistant built with LiveKit Agents, secure tool usage, and switchable model backends for Gemini or OpenAI-style providers.

## O que ele faz

- Conversa por voz em tempo real com persona fixa em PT-BR.
- Pesquisa na web com DuckDuckGo via `ddgs`.
- Consulta clima atual usando Open-Meteo.
- Suporte a três backends por ambiente:
  - `gemini-realtime`
  - `openai-realtime`
  - `openai-compatible-pipeline`
- Fluxo seguro de email com rascunho, allowlist e confirmação explícita.
- Cancelamento de ruído no áudio de entrada.

## Status do projeto

| Item | Status |
| --- | --- |
| CLI do agente (`--help`, `dev`, `start`, `connect`, `console`, `download-files`) | Testado localmente |
| Backend Gemini | Implementado e validado por smoke local |
| Backend OpenAI Realtime | Implementado e validado por instanciamento local |
| Backend compatível com OpenAI | Implementado em modo pipeline e documentado como best-effort |
| Fluxo seguro de email | Implementado e coberto por testes |
| Integração real com providers alternativos | Implementada, mas depende de credenciais externas para teste end-to-end |

## Pré-requisitos

- Python 3.10+
- PortAudio instalado no sistema para `console`
- Conta LiveKit Cloud para `dev`, `start` e `connect`
- Uma das credenciais abaixo:
  - `GOOGLE_API_KEY` para `gemini-realtime`
  - `OPENAI_API_KEY` para `openai-realtime`
  - `OPENAI_API_KEY` e opcionalmente `OPENAI_BASE_URL` para `openai-compatible-pipeline`
- Gmail com App Password apenas se você quiser habilitar envio de email

## Instalação

```bash
git clone https://github.com/seu-usuario/jarvis.git
cd jarvis
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

### PortAudio

```bash
# Ubuntu / Debian
sudo apt-get install -y libportaudio2 portaudio19-dev

# Fedora
sudo dnf install portaudio portaudio-devel

# macOS
brew install portaudio
```

### Modelos locais usados pelo LiveKit

```bash
python3 agent.py download-files
```

## Configuração rápida

### Opção 1: Gemini Realtime

```env
JARVIS_BACKEND=gemini-realtime
GOOGLE_API_KEY=sua-chave-google
GOOGLE_MODEL=gemini-2.5-flash-native-audio-preview-12-2025
GOOGLE_VOICE=Charon
```

### Opção 2: OpenAI Realtime

```env
JARVIS_BACKEND=openai-realtime
OPENAI_API_KEY=sua-chave-openai
OPENAI_REALTIME_MODEL=gpt-realtime
OPENAI_VOICE=marin
```

### Opção 3: Provider compatível com OpenAI

```env
JARVIS_BACKEND=openai-compatible-pipeline
OPENAI_API_KEY=sua-chave
OPENAI_BASE_URL=https://seu-endpoint/v1
OPENAI_LLM_MODEL=gpt-4.1
OPENAI_STT_MODEL=gpt-4o-mini-transcribe
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=ash
```

### LiveKit

Essas variáveis são necessárias para `dev`, `start` e `connect`:

```env
LIVEKIT_URL=wss://seu-projeto.livekit.cloud
LIVEKIT_API_KEY=sua-api-key
LIVEKIT_API_SECRET=seu-api-secret
```

## Matriz de backends

| Backend | Tipo | Variáveis obrigatórias | Observações |
| --- | --- | --- | --- |
| `gemini-realtime` | Realtime | `GOOGLE_API_KEY` | Use um modelo Live, por padrão `gemini-2.5-flash-native-audio-preview-12-2025` |
| `openai-realtime` | Realtime | `OPENAI_API_KEY` | Pode usar `OPENAI_BASE_URL` |
| `openai-compatible-pipeline` | Pipeline | `OPENAI_API_KEY` | Best-effort para endpoints compatíveis |

## Comandos principais

### Checagem de setup

```bash
python3 doctor.py
```

### Gerar token para o playground

```bash
python3 generate_playground_token.py
```

Exemplo com sala fixa:

```bash
python3 generate_playground_token.py --room jarvis-demo --name Gabriel
```

### Ajuda da CLI

```bash
python3 agent.py --help
```

### Console

```bash
python3 agent.py console
```

Modo local com microfone e saída de áudio.

### Dev

```bash
python3 agent.py dev
```

Use com o Playground do LiveKit Cloud.

### Start

```bash
python3 agent.py start
```

Inicia o worker sem auto-reload.

### Connect

```bash
python3 agent.py connect --room minha-sala
```

Conecta o agente a uma sala existente.

### Download de assets do LiveKit

```bash
python3 agent.py download-files
```

## Segurança do email

O envio de email fica desligado por padrão.

Para ativar:

```env
JARVIS_ENABLE_EMAIL_TOOL=true
GMAIL_USER=seuemail@gmail.com
GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
JARVIS_ALLOWED_EMAILS=voce@dominio.com,time@dominio.com
```

Regras atuais:

- O email nunca é enviado no primeiro pedido.
- O agente cria um rascunho e gera um código de 6 dígitos.
- O envio só acontece se o último comando do usuário for exatamente `confirmar <codigo>`.
- Se `JARVIS_ALLOWED_EMAILS` estiver vazio, apenas `GMAIL_USER` pode receber emails.
- O corpo do email e credenciais não são registrados em logs.

## Testes

```bash
python3 -m unittest discover -s tests -v
```

Cobertura desta fase:

- validação de settings
- seleção de backend
- registro dinâmico de tools
- clima
- busca web
- fluxo de email com confirmação e cancelamento

## Troubleshooting

### `python` não existe no terminal

Use `python3` nos comandos.

### `ModuleNotFoundError: No module named 'livekit'`

Ative o ambiente virtual e instale as dependências:

```bash
source venv/bin/activate
python3 -m pip install -r requirements.txt
```

### `Configuração inválida para o backend`

Rode:

```bash
python3 doctor.py
```

O script informa exatamente quais variáveis estão faltando.

### `models/... is not found for API version v1beta`

Isso quase sempre significa que `GOOGLE_MODEL` aponta para um modelo que não é Live. Para o backend `gemini-realtime`, prefira:

```env
GOOGLE_MODEL=gemini-2.5-flash-native-audio-preview-12-2025
```

Evite usar modelos como `gemini-2.5-flash-lite` nesse modo, porque eles não suportam a sessão bidirecional de áudio do Gemini Live.

### `dev`, `start` ou `connect` não sobem

Confira `LIVEKIT_URL`, `LIVEKIT_API_KEY` e `LIVEKIT_API_SECRET`.

### O provider compatível com OpenAI falhou

Esse modo é `pipeline-first` e tratado como best-effort. Confirme se seu endpoint realmente suporta os paths usados por chat, STT e TTS.

## Referências

- [LiveKit Agents](https://docs.livekit.io/agents/)
- [LiveKit Realtime Models](https://docs.livekit.io/agents/models/realtime/)
- [LiveKit OpenAI Plugin](https://docs.livekit.io/agents/models/realtime/plugins/openai/)
- [Google Gemini Live API](https://ai.google.dev/gemini-api/docs/live)
- [Tutorial original que inspirou o projeto](https://youtu.be/An4NwL8QSQ4)
