# Instalação e configuração

## O que precisa

- Python 3.11 ou mais novo (o 3.12 é o que o CI e o passo a passo usam).
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

## Dependências e versões travadas

O `requirements.txt` é um lock: traz todas as dependências, as diretas e as que elas puxam, cada uma com a versão exata (`pacote==1.2.3`). Dois computadores que instalam a partir dele ficam com o mesmo ambiente, e uma versão nova de biblioteca não muda o comportamento do Jarvis sem ninguém ver.

| Arquivo | Para que serve |
| --- | --- |
| `requirements.in` | As dependências diretas, escritas à mão. Só leva um piso (`>=`) quando existe um motivo, comentado na linha. É esse que você edita |
| `requirements.txt` | O lock gerado do `.in`. Não edite à mão |
| `web/package-lock.json` | O mesmo para o Node. O `npm ci` instala exatamente o que está nele |

O lock é universal: o mesmo arquivo vale para Windows, Linux e macOS, e os marcadores de plataforma continuam nele. O `pycaw` e o `comtypes` só entram no Windows (`; sys_platform == 'win32'`) e o `openwakeword` fica de fora no Linux (`; sys_platform != 'linux'`), porque ali ele exige o `tflite-runtime`, sem wheel para o Python 3.12. Para quem só quer instalar, nada muda: `python -m pip install -r requirements.txt` serve em qualquer sistema e instala só o que vale para o seu. Ele foi resolvido para o Python 3.11 ou mais novo: no 3.10 a trava cairia numa versão do `onnxruntime` sem pacote pronto, por isso o piso subiu de 3.10 para 3.11.

Depois de um `git pull` que mexeu no `requirements.txt`, rode o mesmo `pip install -r requirements.txt` de novo. O pip não remove o que saiu do lock; se quiser um ambiente idêntico ao do arquivo, use `uv pip sync requirements.txt` ou recrie o `.venv`.

### Atualizar ou adicionar uma dependência

Precisa do [uv](https://docs.astral.sh/uv/) só para quem mexe no lock (`python -m pip install uv`). Rode sempre na raiz do repositório:

```bash
# regenerar depois de editar o requirements.in (mantém as versões que já estavam, muda só o que mudou no .in)
uv pip compile requirements.in --universal --python-version 3.11 -o requirements.txt

# subir uma dependência (e o que ela puxa) para a versão mais nova
uv pip compile requirements.in --universal --python-version 3.11 -o requirements.txt --upgrade-package livekit-agents

# subir tudo de uma vez (revise o diff e rode os testes)
uv pip compile requirements.in --universal --python-version 3.11 -o requirements.txt --upgrade
```

Depois instale (`python -m pip install -r requirements.txt`), rode `python -m pytest -q tests` e `cd web && npm test && npm run build`, e faça o commit do `.in` e do `.txt` juntos. O `pip-compile` do pip-tools também funciona, mas a linha acima é a que o CI confere. O CI regenera o lock e falha se ele não bate com o `requirements.in` (veja o job `auditoria-python` em [testes.md](testes.md#auditoria-das-dependências)).

No Node: `cd web && npm install <pacote>@<versão>` atualiza o `package.json` e o `package-lock.json`; faça o commit dos dois. O `jarvis.py` roda o `npm install` sozinho quando o `package-lock.json` é mais novo que o `node_modules`.

O Dependabot (`.github/dependabot.yml`) abre toda segunda-feira um PR por ecossistema (pip, npm em `web/` e GitHub Actions) com as atualizações menores juntas. As maiores (major) vêm em PRs separados. Os testes do CI dizem se o PR pode entrar.

### Auditoria

O CI procura vulnerabilidades conhecidas nas versões travadas: `pip-audit` no `requirements.txt` (no Ubuntu e no Windows, porque cada um só enxerga os pacotes do próprio sistema) e `npm audit --omit=dev --audit-level=high` em `web/`. Para rodar no seu computador:

```bash
python -m pip install pip-audit
pip-audit -r requirements.txt --no-deps --disable-pip
cd web && npm audit --omit=dev --audit-level=high
```

Quando a auditoria acha algo, o primeiro caminho é atualizar a dependência (`--upgrade-package`). Se não houver versão corrigida, ou se a atualização quebrar o Jarvis, registre a exceção aqui com o motivo e passe `--ignore-vuln <ID>` no job. Nada de esconder o aviso sem dizer por quê.

Exceções registradas: nenhuma. A auditoria de hoje (`pip-audit` no lock e `npm audit` em `web/`) não achou nada. Ao registrar uma, ponha aqui o ID do alerta, o pacote, o motivo e quando revisar.

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
| `python jarvis.py --rebuild` | Força a recompilação do HUD (ele já recompila sozinho quando o código muda) |
| `python jarvis.py --lan` | Atende também o celular na rede de casa, com HTTPS e pareamento ([celular.md](celular.md)) |
| `python jarvis.py --gestures` | Liga também os gestos das mãos ([gestos.md](gestos.md)) |
| `pythonw jarvis.py --tray` | Só o ícone na bandeja do Windows, sem console e com os logs em `logs/jarvis.log` ([bandeja.md](bandeja.md)) |
| `python gestures.py --preview` | Só os gestos, com a imagem da webcam para testar |
| `python gestures.py --calibrate` | Calibra os gestos para a sua mão |

Depois de atualizar o código não precisa fazer nada: o `jarvis.py` percebe que os arquivos do HUD mudaram desde a última compilação e recompila sozinho ao iniciar. O `--rebuild` continua valendo para forçar. Se o Node não estiver instalado ou a compilação falhar, ele avisa e segue com o HUD que já estava compilado.

### Conferindo a configuração

```bash
python doctor.py
```

Mostra o que está configurado, o que falta no `.env`, a fila de modelos do Gemini e o estado de cada recurso opcional.

```bash
python doctor.py --fontes
```

Consulta de verdade cada serviço da internet que o Jarvis usa (localização de IP, DNS, CNPJ, CEP, cotações, clima, teste de velocidade...) e diz se o formato da resposta continua o que o código lê. Não precisa de `.env` nem de chave. Veja [problemas.md](problemas.md#uma-fonte-externa-falha-no-doctor---fontes).

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
