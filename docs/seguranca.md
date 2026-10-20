# Segurança

O Jarvis lê páginas, pesquisas, notícias, emails e a própria tela. Qualquer um desses textos pode tentar dar ordens a ele (prompt injection). A ideia geral é que ele só age a pedido da sua última fala, com um conjunto fechado de ações, e que tudo que envia, grava ou instala passe por um código falado.

## Controle do computador

O Jarvis não tem terminal nem execução de comandos livres. Em vez disso, existe um conjunto fechado de ações visíveis e reversíveis:

- Abre apps pelo Menu Iniciar e ignora instaladores e desinstaladores.
- Fecha apps como o botão X (`taskkill` sem `/F`). Processos do sistema, o terminal e o Python que rodam o Jarvis e o navegador onde o HUD está aberto são protegidos.
- Só abre endereços `http` e `https`.
- Nunca lê arquivos, senhas, área de transferência ou configurações de rede.
- O prompt manda ignorar ordens vindas de conteúdo da internet. Ações só acontecem a pedido seu.
- Toda ação aparece no registro do HUD e no terminal.

## Confirmação por voz

Enviar email, instalar app, mexer na agenda, cliques arriscados do mouse e ferramentas MCP que escrevem usam o mesmo código de 6 dígitos, que aparece no HUD e o Jarvis fala dígito por dígito. A fala é normalizada antes da comparação, então tudo isto vale para o código 482913:

- "Confirmar 482 913."
- "Jarvis, confirma 4-8-2-9-1-3."
- "Confirmar quatro oito dois nove um três."
- "Confirmar quatrocentos e oitenta e dois, novecentos e treze."

Não valem "pode ir", "manda", "sim", "não confirmar 482913", "confirmar 482913 e ..." (qualquer palavra fora da frase) e frases que não sejam a sua última fala.

Cada tipo pede a sua palavra: "instalação" para instalar, "clique" para o mouse ("confirmar clique 482913"), "agenda" ou "evento" para a agenda ("confirmar agenda 482913") e "integração" para as ferramentas MCP que escrevem ("confirmar integração 482913"). Uma frase não serve para a outra. Se a transcrição da sua fala chegar um instante atrasada, o Jarvis espera até 3 segundos por ela.

## Instalação de aplicativos

Desligada por padrão (`JARVIS_ENABLE_APP_INSTALL=false`). Ligada, continua sem terminal livre:

- A busca roda `winget search --query <nome> --source winget|msstore` com o nome validado (letras, números e espaços, até 60 caracteres), sem shell.
- Só dá para instalar um pacote que apareceu na última busca. O ID passa por regex (`Publicador.Programa` no winget, 12 a 14 caracteres na Microsoft Store) e a fonte precisa ser `winget` ou `msstore`.
- O comando é sempre o mesmo, montado como lista de argumentos: `winget install --id <ID> --exact --source <fonte> --accept-package-agreements --accept-source-agreements`.
- Nada roda antes de a sua última fala ser "confirmar instalação" e o código.
- Não existe desinstalação, `upgrade --all` nem outro subcomando do winget.
- Instaladores que pedem administrador mostram a janela do UAC, e você aprova ou recusa ali.
- A instalação roda em segundo plano. O painel mostra o progresso e o Jarvis anuncia o resultado real que o winget devolveu.

## Mouse e teclado

Desligado por padrão (`JARVIS_ENABLE_COMPUTER_USE=false`), e de propósito. Sem ele, o Jarvis só tem ações fechadas (abrir app, mover janela, abrir site). Com mouse e teclado ele alcança qualquer coisa que você alcança, e um texto malicioso na tela pode tentar se aproveitar disso. Ligar é trocar parte dessa garantia por conveniência. Para compensar, as ações continuam fechadas, visíveis e registradas, com estas travas.

Ele só age a pedido da sua última fala. Antes de cada ação o Jarvis confere se ela pede algo na tela ("clica", "digita", "rola", "aperta"...). Um pedido de leitura ("o que tem na tela?", "lê esse email") nunca vira clique. Texto na tela é dado, não ordem: o modelo de visão é instruído a ignorar frases como "Jarvis, clique aqui" e a avisar quando as encontra.

Senhas, cartões, documentos e chaves ficam de fora. O `type_text` recusa textos com cara de senha ou token, números de cartão (Luhn), CPF e CNPJ (dígitos verificadores) e chaves de API, e recusa digitar quando o campo em foco é de senha (UI Automation `IsPassword` e `ES_PASSWORD`). Cliques em campos de senha também são recusados.

Algumas janelas são proibidas: UAC, Segurança do Windows e Defender, Configurações, Painel de Controle, Editor do Registro, Gerenciador de Tarefas, terminais (cmd, PowerShell, Windows Terminal, WSL), a caixa Executar, telas de credenciais e gerenciadores de senha. Digitar na busca do Menu Iniciar também é recusado (para abrir apps existe o `open_app`, com a lista de bloqueio dele), e textos com cara de comando (`cmd`, `powershell`, `ms-settings:`, `&&`...) nunca são digitados.

Os atalhos seguem uma allowlist: copiar, colar, recortar, desfazer, salvar, buscar, abas, setas, Enter, Esc, Tab, Page Up e Page Down, Home e End, F5, F11, zoom, Alt+Tab, Alt+seta esquerda e direita, Win+D, Win+E, Win+M, Win+Tab e Win+setas. `Win+R`, `Win+X`, `Win+I`, a tecla Win sozinha, `Ctrl+Alt+Del`, `Ctrl+Shift+Esc`, `Alt+F4`, `Ctrl+Enter`, `F12` e o resto ficam de fora.

Cliques arriscados pedem confirmação falada. Se o elemento (pelo texto dele, pela sua descrição ou pela avaliação do modelo) envia, compra, paga, publica, apaga ou confirma algo, nada é clicado: o Jarvis mostra o alvo no HUD, fala um código e só clica depois de "confirmar clique" e o código. Antes de clicar ele confere se a mesma janela continua no lugar, e a confirmação expira em 2 minutos. Enter num app de mensagens ou de email também pede confirmação, a menos que você tenha pedido para enviar.

São no máximo 10 ações por pedido e 8 passos por tarefa, tudo no painel MOU-20 e no terminal. Mexer no mouse, apertar Esc ou dizer "Jarvis, para" interrompe na hora.

O que continua possível, e por isso o padrão é desligado: um clique "inofensivo" induzido por texto na tela quando a sua última fala já pedia alguma ação. E apps que embutem terminal (VS Code, PhpStorm) só são protegidos pelo filtro de comandos. Os prints vão para o Gemini, como na leitura de tela.

## Modo ditado

O texto digitado vem da transcrição do seu microfone, nunca da tela nem do modelo. Enquanto o ditado está ligado, as falas do modelo são interrompidas antes de rodar qualquer ferramenta, e o `click_on_screen`, o `type_text` e as outras ferramentas do MOU-20 recusam com "diga 'fim do ditado' antes".

Valem as mesmas travas da digitação do MOU-20, frase a frase: nada de senhas, cartões, CPF ou CNPJ, chaves ou textos com cara de comando. Campo de senha, UAC, Segurança do Windows, Configurações, terminais, a caixa Executar, a busca do Menu Iniciar e o próprio HUD são recusados. A frase recusada não é digitada e não entra no "desfaz".

"Apaga" e "desfaz" calculam os Backspaces a partir do texto deste ditado, neste campo, e nunca alcançam o que já estava lá.

Esc ou mexer no mouse durante a digitação param na hora e desligam o ditado. Esc entre frases e 3 minutos de silêncio também desligam.

## Gestos e webcam

Os gestos vêm desligados (`JARVIS_ENABLE_GESTURES=false`). Com eles ligados a webcam fica acesa, e "desliga os gestos" a libera.

Nada é gravado nem enviado. Cada quadro é processado na memória, neste computador, e descartado. O modelo do MediaPipe roda local, e só eventos curtos (como "janela para o monitor de cima") vão para o HUD local. O painel de gestos mostra a câmera e as miniaturas das janelas só no seu monitor e fica fora dos prints que o Jarvis tira da tela.

Os gestos são um conjunto fechado de ações, as mesmas da voz: mover, maximizar, minimizar, desfazer, fechar, trocar de aba, o mouse no ar e, nos personalizáveis, mídia, volume, microfone do Jarvis, layouts, abrir um app ou site e atalhos de teclado. Não existe gesto para digitar, apagar ou rodar comandos, e atalhos que fecham ou apagam são recusados.

Fechar por gesto exige o polegar para baixo segurado, com contagem visível, e respeita as mesmas proteções da voz: processos do sistema, o terminal e o Python do Jarvis e a aba do HUD não fecham.

O agente só liga e desliga os gestos (`gesture_control`) e muda o mapeamento a seu pedido (`gesture_shortcuts`). Quem faz o gesto é a sua mão. Cada ação aparece no registro do HUD e no terminal.

O painel Gestos do HUD muda o mapeamento pela API `/api/gestures`, com as mesmas recusas da voz. Ela só atende o próprio computador ou um celular pareado e recusa pedidos vindos de outro site aberto no navegador (`Sec-Fetch-Site`). Os botões de ligar, armar e mouse no ar passam pelo agente, numa chamada RPC dentro da sala do LiveKit.

Tapar a câmera é o único gesto que funciona desarmado, e só quando a mão apareceu logo antes e a imagem estava normal. Apagar a luz ou começar com a tampa fechada não muta nada.

## Câmera

Vem desligada (`JARVIS_ENABLE_CAMERA=false`). Desligada, o servidor nunca abre a webcam e recusa os endpoints da câmera.

Ela liga só sob demanda (painel Câmera aberto, uma foto pedida ao Jarvis ou outro recurso usando) e desliga sozinha uns 3 segundos depois que ninguém mais usa, apagando a luz da webcam. "Jarvis, desliga a câmera" ou o botão do painel cortam tudo na hora.

Enquanto a webcam está ligada, o aviso CÂMERA ATIVA fica sempre visível no HUD, por cima de qualquer painel, não importa quem a ligou.

Nada é gravado em disco: os quadros ficam só na memória do servidor. Uma foto só vai para o Gemini quando você pede para o Jarvis olhar (`look_at_camera`), e ela aparece no painel Câmera como "Analisado" para você ver exatamente o que foi enviado. O feed ao vivo nunca sai do computador.

Os endpoints da câmera só atendem este computador. Eles recusam outro `Host` (DNS rebinding) e pedidos vindos de outros sites abertos no navegador (`Sec-Fetch-Site`), que poderiam tentar ligar a webcam com um `<img>`.

## Presença

Vem desligada (`JARVIS_PRESENCE=false`) e só funciona com a câmera habilitada.

Os quadros ficam só na memória e são descartados logo depois da detecção. Nenhuma imagem é gravada nem enviada, e a presença não manda nada ao Gemini. O resumo das boas-vindas sai do diário local do servidor, só com texto curto ("o timer 'chá' terminou às 15:02").

O cadastro do rosto é opcional e guarda apenas embeddings em `presenca_rosto.json`, ignorado pelo git. `python presence.py --forget` apaga.

Os endpoints `/api/presence` (estado e ações), `/api/presence/note` e `/api/presence/welcome` têm a mesma proteção da câmera: só este computador e só o próprio HUD (`Host` e `Sec-Fetch-Site`).

A presença só pausa mídia e bloqueia a tela. Ela não fecha, não digita e não envia nada.

## Leitura de tela

O `look_at_screen` só roda quando você pede. O print aparece no HUD e é enviado ao Gemini (Google) para análise, com tudo que estiver visível naquela tela ou janela. Feche arquivos sensíveis, como o `.env`, antes de pedir. O Jarvis é instruído a nunca ler senhas, chaves ou tokens em voz alta.

O assistente de tela (TEL-31) também só roda quando você pede e envia ao Gemini o texto lido (ou o print, quando não há texto). Antes de sair do computador, chaves de API, tokens, chaves privadas e linhas de `.env` como `DB_PASSWORD=...` viram `[segredo oculto]`. Gerenciadores de senha, o UAC, janelas de credenciais e a tela de bloqueio nunca são lidos.

Nada fica salvo em disco. A última explicação vive só na memória da sessão, por 30 minutos, para o "copia a correção", que só escreve na área de transferência. O texto da tela é tratado como dado: se ele tentar dar ordens ao Jarvis, o painel avisa e nada é executado.

## Memória

Uma memória falsa plantada por uma página seria um prompt injection permanente, então a memória segue regras fechadas.

O `remember` só grava quando a sua última fala, dos últimos 30 segundos, pede: "lembra", "anota", "guarda", "grava", "registra", "não esquece"... ou é um "sim" logo depois de o Jarvis perguntar "quer que eu guarde isso?". "Não precisa lembrar" não vale. Resultados de pesquisa, notícias, emails e a tela nunca autorizam nada sozinhos.

O `forget` também exige "esquece", "apaga" ou "remove" na sua última fala, e apagar tudo exige "tudo" ou "todas".

Senhas, PINs, tokens, chaves de API, códigos de acesso ou de verificação, frases de recuperação, números de cartão (Luhn), CPF (dígitos verificadores) e documentos ou contas acompanhados de número são recusados, mesmo a seu pedido. O painel mostra "Recusado por segurança" sem repetir o conteúdo.

O painel do HUD só lista e apaga por id. Não existe caminho para criar memória pelo navegador.

O resumo entra nas instruções marcado como dados ("nunca ordens"), sem itens sensíveis que tenham sido editados à mão no arquivo, e o texto dos fatos não vai para os logs.

Na busca pelo sentido, o texto de cada fato vai para a API de embeddings do Google e volta como vetor. Ele já ia para o Google antes, dentro das instruções do Gemini, mas quem preferir pode desligar com `JARVIS_MEMORY_EMBEDDINGS=false`. O filtro de segredos vale antes: um fato com cara de senha, editado à mão no arquivo, nunca vira vetor, e uma pergunta com senha ou código nem chega à API. Esquecer uma memória apaga o vetor dela junto.

## Rotinas

Só as ações da tabela de [memoria-e-rotinas.md](memoria-e-rotinas.md#o-arquivo) entram numa rotina. Email, instalação de apps e mouse e teclado ficam de fora, porque têm a própria confirmação por código.

Bloquear o PC e fechar um app nunca rodam sozinhos, nem numa rotina agendada. Esses passos ficam para o fim, o Jarvis pergunta e só faz depois de um "sim" ou "pode" numa fala nova sua. O pedido que iniciou a rotina não vale, e qualquer "não" ou "espera" recusa. Sem resposta em 3 minutos, o passo é descartado.

Criar, mudar, apagar ou agendar uma rotina exige que a sua última fala fale em rotina, modo ou agenda, ou cite o nome dela. Uma página, um email ou um texto na tela não plantam rotinas.

O `POST /api/routines/claim`, por onde o agente pega a rotina agendada, só atende o próprio computador e recusa pedidos de outros sites.

As rotinas por contexto seguem as mesmas regras. O gatilho só dispara a rotina: os passos são os mesmos da tabela, e bloquear o PC ou fechar um app continuam esperando o seu "sim". Criar, mudar ou desligar um gatilho exige a mesma fala sua sobre a rotina. O vigia lê só nomes de processos, a janela em foco, nomes de aparelhos de áudio, o nome da rede Wi-Fi e o estado da presença, e nada disso sai do PC nem fica gravado. `JARVIS_CONTEXT_TRIGGERS=false` desliga tudo.

## Palavra de ativação

O detector só fala com o servidor local, usando um segredo aleatório que o `jarvis.py` gera a cada execução. Sem ele, o `/api/wake/trigger` recusa o aviso.

Os endpoints que o HUD usa (`/api/wake/events`, `/hud` e `/result`) recusam pedidos de outros sites (`Sec-Fetch-Site`), então uma página aberta no navegador não consegue abrir o link nem desligar o detector.

A ativação só conecta o mesmo link do botão Inicializar. As regras de email, instalação e controle do PC continuam iguais.

O detector analisa o som no próprio PC e só manda ao servidor local a palavra ouvida e a pontuação. Nada é gravado, e nenhum áudio vai para o Gemini ou o LiveKit antes de o link abrir. A palavra só pode trocar a persona por uma das conhecidas, e só quando o aviso foi aceito (sem link aberto).

## Personas

A troca de persona do HUD (`POST /api/persona`) só grava um dos quatro nomes conhecidos no `persona.json` e tem a mesma proteção do painel Gestos: só o próprio computador ou um celular pareado, nunca outro site aberto no navegador. A persona muda o jeito de falar e a voz, nunca as travas: códigos de confirmação, recusas e permissões são as mesmas em todas.

## Google Agenda

O login é OAuth de app para computador, com a permissão mínima `calendar.events`. O token (`google_token.json`) e as credenciais do app (`google_credentials.json`) ficam só na pasta do projeto, fora do git. Quem tiver o token lê e mexe na sua agenda, então não compartilhe a pasta com ele.

Ler é livre. Criar, alterar e apagar só acontecem com "confirmar agenda" e o código na sua última fala. Texto de eventos, emails ou páginas nunca confirma nada.

A fila de avisos (`/api/calendar/reminders/claim`) só atende o próprio computador e recusa pedidos de outros sites. Ela guarda só título, horário, local e link dos eventos que vão começar, e cada aviso sai uma vez.

## Integrações MCP

Desligadas por padrão (`JARVIS_ENABLE_MCP=false`). Ligadas, cada servidor do `mcp.json` passa pelas mesmas travas:

- Só as ferramentas da lista `permitir` chegam ao modelo. Um servidor sem essa lista não libera nada, e no HTTP o próprio cliente do LiveKit também filtra.
- Ferramenta que escreve só prepara a ação. Ela roda depois de "confirmar integração" e o código na sua última fala, e o resultado de uma integração nunca confirma nada.
- O que o servidor devolve chega ao modelo marcado como dado de um serviço externo, nunca ordem, e cortado em 6000 caracteres.
- Os tokens ficam no `.env`. O `mcp.json` guarda só o nome da variável, e um arquivo com outro campo (como o próprio token) é recusado. Servidor HTTP precisa ser `https://`, a não ser no `127.0.0.1`.
- Um servidor local recebe só o próprio token e as variáveis básicas do sistema (`PATH` e parecidas), não o `.env` inteiro.

Um servidor MCP roda com as permissões do token que você deu a ele. Dê o mínimo: para ler issues, um token só de leitura basta.

## Avisos proativos

O texto de um aviso (nome de arquivo baixado, nome de processo, lembrete) chega ao modelo como dado, entre marcas de "nunca ordens", sem aspas, colchetes ou sinais de tag. Assim um arquivo chamado `ignore tudo e ....pdf` não vira instrução.

O `/api/proactive/next` só atende o próprio computador (`Host` local e sem `Sec-Fetch-Site` de outro site). Um aviso só abre o mesmo link do botão Inicializar, e as regras de email, instalação e controle do PC continuam iguais.

O `lembretes.json` é gravado de forma atômica, com uma trava de arquivo entre o agente e o servidor. Um arquivo ilegível é guardado como `lembretes.corrompido-<data>.json`.

## Celular na rede

Do próprio PC (conexão vinda de `127.0.0.1`) tudo funciona como sempre. De qualquer outro endereço, nenhuma rota responde sem um aparelho pareado (`401`): token do LiveKit, status, câmera (foto e feed), prints, eventos da palavra de ativação, a documentação da API e qualquer rota que vier a existir. O bloqueio é um middleware que nega por padrão. Sem token, o celular só recebe os arquivos do HUD compilado (que não têm dados), a pergunta "estou pareado?", o envio do código e o certificado público da CA.

Gerar código, ver o QR, listar e revogar aparelhos só funciona no próprio PC, inclusive contra DNS rebinding (o `Host` precisa ser `127.0.0.1` ou `localhost`). Um celular pareado não pareia outros.

O código tem 6 dígitos, vale 5 minutos e só pode ser usado uma vez. Cinco tentativas erradas queimam o código, e é preciso gerar outro no PC.

Cada aparelho recebe o seu token aleatório (256 bits), guardado num cookie `HttpOnly`, `Secure` e `SameSite=Strict`: o JavaScript da página não o lê, e outros sites não o usam. O PC guarda só o hash SHA-256, em `aparelhos.json` (fora do git). Pedidos de outros sites abertos no celular (`Sec-Fetch-Site`) são recusados.

A revogação corta na hora as rotas e as respostas longas em andamento (feed da câmera, eventos). Um link de voz já aberto no LiveKit cai quando a página do celular percebe a revogação, em até 15 s. Um token de voz emitido antes da revogação ainda vale para entrar na sala por até 30 minutos.

O tráfego do celular é HTTPS com a CA local, restrita por Name Constraints a IPs privados e `.local`. A chave da CA fica em `.jarvis-tls/jarvis-ca.key`, só no PC.

Não abra a porta 8000 no roteador. O modo `--lan` é só para a rede de casa e atende apenas os IPs privados do PC (`192.168.*`, `10.*` e de `172.16.*` a `172.31.*`).

## Rede e credenciais

O servidor do HUD escuta apenas em `127.0.0.1` por padrão. Para usar o celular, use `--lan` ([celular.md](celular.md)), nunca `--host 0.0.0.0`: sem o modo `--lan` não há HTTPS, e o celular nem consegue usar o microfone.

O `.env` nunca vai para o navegador. O `/api/status` só informa se cada item está configurado.

## Email

O email vem desligado. Para ligar:

```env
JARVIS_ENABLE_EMAIL_TOOL=true
GMAIL_USER=seuemail@gmail.com
GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
JARVIS_ALLOWED_EMAILS=voce@dominio.com,time@dominio.com
```

Endereços ditados ("gabriel m silva arroba gmail ponto com") são montados pelo `check_email_address` e lidos de volta para você confirmar antes do rascunho. Se o endereço montado não estiver autorizado mas for parecido com um autorizado, o Jarvis pergunta se é esse.

Nunca é enviado no primeiro pedido. O agente cria um rascunho com um código de 6 dígitos (que também aparece no HUD) e fala o código dígito por dígito. O envio só acontece se a sua última fala for "confirmar" e o código (veja [Confirmação por voz](#confirmação-por-voz)).

Com `JARVIS_ALLOWED_EMAILS` vazio, só o próprio `GMAIL_USER` pode receber. O corpo do email e as credenciais não vão para os logs.
