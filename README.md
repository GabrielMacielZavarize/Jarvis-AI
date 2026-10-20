# J.A.R.V.I.S.

Assistente de voz para o PC, inspirado no Jarvis do Homem de Ferro. Você fala, ele responde na hora e faz as coisas no computador: abre apps, arruma as janelas nos monitores, toca música, marca reunião, lembra do que você pediu e explica o erro que está na tela. Tudo aparece num HUD 3D no navegador, com um núcleo de energia que reage à voz e painéis que surgem quando ele usa uma ferramenta.

Por baixo, um worker do [LiveKit Agents](https://docs.livekit.io/agents/) conversa com o Gemini Live (padrão, funciona no plano gratuito) ou com o OpenAI Realtime. O HUD é React com Three.js e recebe o resultado das ferramentas pelo data channel do LiveKit.

In English: real-time voice assistant built on LiveKit Agents (Gemini Live or OpenAI Realtime) with a React Three Fiber holographic HUD. Tools push structured results to the HUD over the LiveKit data channel.

## O que ele faz

- Conversa por voz no tom do filme: mordomo britânico, calmo e com humor seco. A voz dá para trocar falando.
- Tem quatro personas que mudam a identidade inteira: J.A.R.V.I.S., Mark III (o computador da armadura), F.R.I.D.A.Y. (voz feminina, direta, que chama você de "chefe") e Stealth (discreto, em voz baixa). Cada um tem persona, voz, núcleo 3D, painéis e sons próprios, e troca no meio da conversa.
- Abre e fecha apps, sites e abas, controla mídia e volume, move janelas entre os monitores e salva layouts.
- Clica, digita e rola a tela por você, e tem um modo ditado que escreve no campo em foco o que você fala.
- Lê a tela e explica erros, código e páginas, com a correção pronta para copiar.
- Fica de olho no terminal ou no PhpStorm e avisa quando aparece um erro novo, oferecendo a explicação.
- Resume cada conversa num diário e responde "o que eu te pedi ontem?" e "onde paramos no projeto?".
- Guarda fatos entre conversas, roda rotinas ("bom dia, Jarvis", "modo foco", também sozinhas quando você abre um app ou conecta o fone) e avisa sozinho de lembretes, bateria, downloads e reuniões.
- Lê e mexe no Google Agenda, manda email e instala apps pelo winget. O que grava ou envia só acontece depois de um código falado.
- Usa as ferramentas de servidores MCP (GitHub, Notion, Spotify...) com as mesmas travas: só o que você liberar, e o que escreve pede código.
- Controla a casa pelo Home Assistant: apaga a luz, liga o ar e diz se a porta está trancada. Destrancar porta, abrir portão e mexer em alarme ou câmera pedem código.
- Olha pela webcam quando você pede, percebe quando você sai e volta e entende gestos das mãos para mexer nas janelas. Um painel no HUD mostra os gestos ao vivo e deixa trocar o que cada um faz.
- Acorda quando você diz "Jarvis" (ou "Friday", que já abre a F.R.I.D.A.Y.) e também funciona pelo celular, na rede de casa.
- Se o modelo gratuito do Google estoura a cota ou trava, a conversa continua em outro modelo sem cair.

Quase tudo que mexe no PC vem desligado e liga por variável no `.env`. A lista completa está em [docs/protocolos.md](docs/protocolos.md).

## Começando

Precisa de Python 3.10 ou mais novo, Node.js 20 ou mais novo, uma conta no [LiveKit Cloud](https://cloud.livekit.io) e uma chave do Gemini (grátis no [AI Studio](https://aistudio.google.com/apikey)).

No Windows:

```powershell
git clone https://github.com/GabrielMacielZavarize/Jarvis-AI.git
cd Jarvis-AI
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
python agent.py download-files
```

O mínimo no `.env`:

```env
LIVEKIT_URL=wss://seu-projeto.livekit.cloud
LIVEKIT_API_KEY=sua-api-key
LIVEKIT_API_SECRET=seu-api-secret
GOOGLE_API_KEY=sua-chave-google
```

E para subir:

```bash
python jarvis.py
```

Na primeira vez ele compila o HUD, sobe o agente e o servidor em `http://127.0.0.1:8000` e abre o navegador. Clique no núcleo (ou aperte Espaço) e fale. `python doctor.py` confere se a configuração está certa.

Sem LiveKit dá para ver o HUD no modo simulação: `python jarvis.py --no-agent` e o botão Simulação.

Linux, macOS, OpenAI e as demais opções estão em [docs/instalacao.md](docs/instalacao.md).

## Documentação

| Assunto | Onde |
| --- | --- |
| Instalação, `.env`, backends e como rodar | [instalacao.md](docs/instalacao.md) |
| Modelos do Gemini, cota e tempo de resposta | [modelos.md](docs/modelos.md) |
| Protocolos (ferramentas) e o que liga cada um | [protocolos.md](docs/protocolos.md) |
| HUD: visual, personas, atalhos e simulação | [hud.md](docs/hud.md) |
| Palavra de ativação, voz e persona | [voz.md](docs/voz.md) |
| Apps, monitores, layouts, mídia e winget | [computador.md](docs/computador.md) |
| Mouse, teclado e modo ditado | [mouse-e-ditado.md](docs/mouse-e-ditado.md) |
| Assistente de tela e vigia de janela | [assistente-de-tela.md](docs/assistente-de-tela.md) |
| Gestos das mãos | [gestos.md](docs/gestos.md) |
| Câmera e presença | [camera-e-presenca.md](docs/camera-e-presenca.md) |
| Memória e rotinas | [memoria-e-rotinas.md](docs/memoria-e-rotinas.md) |
| Diário das conversas | [diario.md](docs/diario.md) |
| Google Agenda | [agenda.md](docs/agenda.md) |
| Integrações MCP (GitHub, Notion...) | [integracoes.md](docs/integracoes.md) |
| Casa inteligente (Home Assistant) | [casa.md](docs/casa.md) |
| Avisos e lembretes | [avisos.md](docs/avisos.md) |
| Celular na rede de casa | [celular.md](docs/celular.md) |
| Segurança | [seguranca.md](docs/seguranca.md) |
| Arquitetura e arquivos | [arquitetura.md](docs/arquitetura.md) |
| Testes automáticos | [testes.md](docs/testes.md) |
| Quando algo dá errado | [problemas.md](docs/problemas.md) |
| Checklist para testar tudo em casa | [ROTEIRO_DE_TESTES.md](docs/ROTEIRO_DE_TESTES.md) |

## Testes

```bash
python -m unittest discover -s tests -v
cd web && npm test && npm run build
```

Os testes usam mocks e não mexem em nada do seu computador. O que só dá para conferir na máquina real (webcam, microfone, monitores, Google e celular) está no [roteiro de testes](docs/ROTEIRO_DE_TESTES.md).

## Créditos

O projeto começou a partir [deste tutorial](https://youtu.be/An4NwL8QSQ4). Outras referências estão em [docs/arquitetura.md](docs/arquitetura.md#referências).
