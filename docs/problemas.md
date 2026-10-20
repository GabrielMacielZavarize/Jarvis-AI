# Quando algo dá errado

Antes de tudo, rode `python doctor.py`. Ele mostra o que falta no `.env` e o estado de cada recurso.

## O Jarvis demora para responder

Olhe o "Tempo de resposta" no painel Sistema e o terminal do agente. Até 1,5 s é o normal do Gemini Live. Acima disso, as causas mais comuns são estas.

O modelo está sobrecarregado ou sem cota. Acontece no plano gratuito em horário de pico. Com `GOOGLE_FALLBACK_MODELS` a conversa passa para outro modelo, e `JARVIS_MODEL_ROTATION=rotate` divide o uso entre eles ([modelos.md](modelos.md)).

O Gemini demora a perceber que você terminou de falar. Barulho de fundo ou um microfone sensível esticam o turno. Teste `JARVIS_END_OF_SPEECH_MS=500` e um fone com microfone.

O modelo pensa antes de falar. O `gemini-3.8-live-extended-thinking` responde mais devagar; prefira o `gemini-3.8-live`.

É uma ferramenta de internet. Clima, pesquisa e notícias esperam o site responder (até 15 s), e a placa sobre o núcleo mostra quando é isso.

## "Python was not found" no Windows

O comando `python` pode ser só o atalho da Microsoft Store. Instale o Python (por exemplo `winget install Python.Python.3.12`) e use o do venv: `.venv\Scripts\python.exe`.

## O HUD diz "Configuração pendente"

O painel Sistema lista exatamente o que falta no `.env`. O servidor relê o `.env` a cada requisição, então basta salvar o arquivo e esperar alguns segundos.

## O link conecta mas o Jarvis não responde

O worker precisa estar rodando. O `python jarvis.py` já sobe ele; separado, é `python agent.py dev`. O HUD avisa depois de alguns segundos se nenhum agente entrar na sala.

## O microfone não funciona

O navegador só libera o microfone em `localhost`, `127.0.0.1` ou HTTPS. Em Ajustes, no painel Sistema, escolha o microfone certo e veja se o medidor "Entrada de voz" se mexe. Quando o agente detecta a sua voz, o painel mostra "Ouvindo sua voz agora" e o terminal registra `Voz do usuário detectada.`

## O link fecha sozinho

Confira `JARVIS_WAKE_SILENCE_SECONDS` no `.env`. O valor do `.env` vale mais que o padrão do código, então um `30` que sobrou de antes faz o link fechar depois de 30 s de silêncio. Use `0` para ele só fechar com "tchau, Jarvis" ou o botão. O `python doctor.py` mostra "Link fecha sozinho: nunca" quando está certo.

## Falo "Jarvis" e nada acontece

Se o painel Sistema diz "Detector offline", veja as linhas `[ATIVAÇÃO]` no terminal. Se falta pacote, rode `pip install openwakeword sounddevice`.

Se diz "Aguardando “Jarvis”" mas não ativa, rode `python wake_word.py --test` e veja o pico da sua fala. Ajuste o `JARVIS_WAKE_THRESHOLD` para um pouco abaixo dele, ou diga "hey Jarvis".

Se diz "Sem sinal no microfone", o dispositivo está mudo no Windows (tecla de mudo do notebook ou Configurações > Sistema > Som > Entrada). O terminal mostra qual microfone o detector abriu.

Se é o microfone errado, escolha o certo no painel Sistema (o detector troca na hora) ou fixe um com `JARVIS_WAKE_MIC`.

Se ativa sozinho com TV ou música, suba o `JARVIS_WAKE_THRESHOLD` para 0.6 ou 0.7.

## O Jarvis não avisa sozinho

Confira `JARVIS_PROACTIVE=true`, se o painel Sistema mostra "Avisos proativos · PRO-28" e o horário de silêncio ("o que você está vigiando?"). Avisos de prioridade normal com o link fechado aparecem só no HUD, de propósito. No terminal, cada aviso gera uma linha `Aviso proativo (<assunto>, <rota>)`. Para um lembrete que abre o link, o LiveKit precisa estar configurado, e o Chrome pode exigir um clique para tocar o som ("Clique para ouvir o Jarvis").

## A rotina agendada não rodou

O agendador roda dentro do `python jarvis.py`. Com ele fechado, ou com o PC dormindo até mais de 10 minutos depois do horário, a rotina daquele dia não roda.

Pergunte "quais rotinas eu tenho?" para ver se ela aparece como agendada, e confira `JARVIS_ENABLE_ROUTINES=true` (vem ligado).

Se o navegador abriu mas o link não conectou, veja no registro de atividades do HUD a linha "Rotina agendada" e a mensagem do LiveKit. O pedido espera 3 minutos pelo link antes de ser descartado.

## O Spotify abre mas não começa a tocar

O Jarvis confere o título da janela do Spotify. Quando ele não muda para "Artista - Música", o Jarvis diz que só abriu (ou que só abriu a busca) e pede para você apertar play. Isso acontece quando a pesquisa web não acha um link de faixa ou álbum, quando a versão do app não começa a tocar ao abrir links `spotify:` ou quando o Spotify fica escondido na bandeja sem janela. Garantir a reprodução exigiria a Spotify Web API (app no Spotify Developer Dashboard, login OAuth e conta Premium), que não está configurada.

## O Jarvis não consegue focar a janela do navegador

O Windows às vezes impede que outro programa traga uma janela para frente. Se o comando de abas falhar, clique uma vez no navegador e peça de novo.

## "models/... is not found for API version v1beta"

O `GOOGLE_MODEL` aponta para um modelo que não é Live. No backend `gemini-realtime`, use `gemini-3.8-live` ou outro modelo com `live` ou `-native-audio` no nome. Com modelos de reserva configurados, a conversa passa para o próximo e o painel Sistema mostra "Modelo · reserva".

## O provider compatível com OpenAI falhou

Esse modo é `pipeline-first` e funciona no melhor esforço. Confirme se o endpoint tem os paths de chat, STT e TTS.

## Uma integração MCP aparece como indisponível

`python mcp_client.py` mostra o motivo de cada servidor. Os mais comuns: o token não está no `.env` com o nome do `token_env`, o `permitir` está vazio, o `npx` não está instalado (precisa do Node.js) ou o servidor demorou mais que `JARVIS_MCP_TIMEOUT` para subir. Na primeira vez o `npx` baixa o pacote do servidor, o que pode passar dos 8 segundos; rode `python mcp_client.py` uma vez antes ou aumente o tempo. Detalhes em [integracoes.md](integracoes.md).

## O ícone da bandeja não aparece

Confira o fim do `logs/jarvis.log`. Se lá diz que a porta já está em uso, outro Jarvis ficou aberto: feche pelo ícone dele ou pelo Gerenciador de Tarefas (processos `pythonw.exe`). O Windows às vezes esconde ícones novos na seta ao lado do relógio; arraste o do Jarvis para a barra. Se o item Iniciar com o Windows está marcado mas o Jarvis não abre no login, veja se ele não foi desativado em Configurações, Aplicativos, Inicialização. Detalhes em [bandeja.md](bandeja.md).

## Câmera em uso

Os gestos ainda abrem a webcam por conta própria, fora do hub do servidor. Com presença e gestos ligados ao mesmo tempo, o Windows pode recusar a segunda abertura. Use um dos dois por vez se a sua webcam não aguentar.
