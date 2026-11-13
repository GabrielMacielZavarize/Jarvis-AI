# HUD

O HUD roda no navegador (React com Three.js) e é servido pelo `server.py` em `http://127.0.0.1:8000`.

## O que aparece na tela

No centro fica o núcleo de plasma, feito com shader, rodeado por anéis com marcações, órbitas giroscópicas, um disco de partículas e a grade holográfica no piso, tudo com bloom. Ele reage em tempo real ao áudio do Jarvis e do seu microfone e muda de cor com o estado: ouvindo, processando ou respondendo. Ao processar, o HUD inteiro fica âmbar. Numa falha, vermelho. As cores deslizam em 0,8 s em vez de trocar de uma vez, e um "processando" curto antes da voz ou as pausas entre frases não repintam o HUD, para ele não piscar a cada turno da conversa.

Os painéis são planos, de frente para você, com texto maior e mais contraste que antes. Cada coluna rola sozinha: um painel a mais nunca corta o de baixo.

### Áreas de trabalho

As abas no topo (no celular, a barra de baixo) trocam o que o HUD mostra. O dock com Inicializar, microfone e a legenda fica à mão em todas.

| Área | Tecla | O que tem |
| --- | --- | --- |
| Painel | `1` | O núcleo no centro, o Briefing e as Projeções à esquerda, a Transcrição e o Registro à direita |
| Dia a dia | `2` | Tarefas e notas com caixa de marcar, a sessão de foco, as cotações e o teste da internet ([dia-a-dia.md](dia-a-dia.md)) |
| Olho de Deus | `3` | Consultas em fontes públicas: um campo que reconhece IP, domínio, link, CNPJ, CEP, DDD, email ou usuário, a checagem de senha vazada e os resultados da sessão ([olho-de-deus.md](olho-de-deus.md)) |
| Sistema | `4` | Estado do link e do modelo, tempo de resposta, voz, ativação por voz, presença, o painel de Saúde, o do Celular, os Gestos e a lista de Protocolos com o que está ligado no `.env` |
| Ajustes | `5` | Aparência (persona, tamanho do texto, alto contraste, qualidade da cena, legenda, modo ambiente, som do reator), Áudio (microfone, medidores e sons da interface) e a lista de atalhos |

Fora do Painel o núcleo recua para o fundo e os painéis da área ocupam a tela. `Esc` volta ao Painel.

### Briefing

O primeiro painel do Painel junta o que importa agora: a saudação pela hora, o clima da `JARVIS_HOME_CITY`, a próxima reunião (com a [agenda](agenda.md) ligada), as primeiras tarefas abertas (que dá para marcar ali mesmo), os lembretes das próximas 24 horas, dólar, euro e bitcoin, as manchetes, o que pede atenção (configuração pendente, servidor fora do ar, microfone sem sinal) e três frases de exemplo dos protocolos ligados, que mudam a cada dia. É o mesmo resumo que o Jarvis fala com "como está o meu dia?" ([dia-a-dia.md](dia-a-dia.md#briefing-do-dia-brf-46)). Com o link aberto, clicar numa frase manda o pedido por texto.

Quando o Jarvis projeta um painel, o Briefing encolhe para uma linha e deixa o espaço para as projeções. A setinha do cabeçalho abre e recolhe na mão.

### Projeções

Quando o Jarvis usa uma ferramenta, um painel holográfico se projeta na coluna das Projeções: clima com previsão de 5 dias e o globo girando até a cidade, resultados de pesquisa, notícias, relógio mundial, diagnóstico do PC, timers com contagem regressiva, notas, rascunhos de email e os painéis de cada protocolo. Uma placa sobre o núcleo mostra o protocolo em execução (código, nome e alvo) e depois o resultado.

Enquanto ele pensa ou busca algo na internet, o núcleo vira um globo que desenha arcos da sua cidade até os serviços consultados. Nas pesquisas o globo cresce, os anéis recuam e cada destino ganha um rótulo com a cidade e o serviço.

Também tem a transcrição ao vivo da conversa (com hora), a linha de comando para mandar texto em vez de falar, o registro de atividades em linha do tempo, o radar no piso e o feixe de luz do projetor. O boot mostra o anel do reator se completando e os painéis entram em cascata depois dele.

### Paleta de comandos

`Ctrl+K` (ou a lupa nas abas e no dock) abre uma busca com tudo o que o HUD faz por clique: ir para uma área, iniciar e encerrar o link, microfone, simulação, as quatro personas, começar e encerrar o foco, modo cinema, legenda, modo ambiente, qualidade da cena e restaurar os painéis, texto maior, menor e de volta a 100% e o alto contraste (ligar, desligar, automático). Os protocolos ligados também aparecem, cada um com uma frase de exemplo que vai por texto ao Jarvis. Digitar um IP, domínio, link, CNPJ, CEP ou email oferece a consulta no Olho de Deus como primeira opção. Com o link aberto, o que você digitar e não for um comando vira "Enviar ao Jarvis". Setas navegam, `Enter` executa e `Esc` fecha. A busca ignora acentos.

## Ajustes

É a última área (tecla `5`, ou o botão Ajustes do painel Sistema). Tudo que você muda ali é salvo no navegador.

### Personas

J.A.R.V.I.S. (o padrão), Mark III, F.R.I.D.A.Y. e Stealth. Cada persona muda a identidade inteira, não só as cores: quem responde e com que voz, o núcleo 3D, o formato dos painéis, as fontes, o boot e os sons. Detalhes em [O que cada persona muda](#o-que-cada-persona-muda), mais abaixo. Também dá para trocar por voz: "Jarvis, chama a Friday", "modo Mark III", "modo discreto", "volta ao normal", "deixa roxo".

### Tamanho do texto

Seis passos: 90%, 100% (o de fábrica), 110%, 120%, 130% e 140%. Escolha em Ajustes › Aparência (Tamanho do texto) ou na paleta (`Ctrl+K`: "texto maior", "texto menor", "tamanho do texto: 100%"). Vale para o HUD inteiro, no computador e no celular, e fica salvo neste navegador: o celular guarda o dele, separado do PC.

Como funciona, para quem for mexer no CSS:

- `prefs.ts` põe `--ts` (0,9 a 1,4) no `<html>`, e todo `font-size` dos arquivos de `web/src/styles/` é `calc(12px * var(--ts, 1))`. Texto novo no CSS segue a mesma forma, senão fica de fora da preferência.
- O que é grande por enfeite cresce só metade (`--ts-big`): o nome da marca, o relógio, os títulos do boot e das áreas. Os rótulos da barra de baixo do celular crescem um quarto (`--ts-nav`), porque são seis em uma tela estreita, e nela o nome da aba usa a fonte de interface (Rajdhani, mais estreita) em todas as personas: com Orbitron, Teko ou Exo 2 o nome já saía cortado em telas de 360 px, mesmo a 100%. O número dentro dos medidores do diagnóstico (um SVG de tamanho fixo) não muda.
- As colunas laterais do Painel alargam 40% da diferença (a 140%, uns 16% mais largas). A conta está em `--side`, em `global.css`.
- Botões ganham altura em vez de cortar o rótulo quando ele quebra em duas linhas, o cabeçalho dos painéis passa o contador para a linha de baixo, e a legenda embaixo do núcleo nunca fica mais larga que a coluna do meio.
- A partir de 120% (`data-text-large` no `<html>`) as abas do topo guardam o nome só da aberta, o resto vira ícone, e a frase da marca some, para a marca, as abas e o relógio caberem na mesma linha.
- As colunas continuam rolando sozinhas. No celular os campos nunca passam a ficar abaixo de 16 px (o iPhone dá zoom em campo menor), mesmo a 90%.

O teste `com o texto a 140% nada fica cortado…` (`web/e2e/acessibilidade.e2e.ts`) abre as cinco áreas nas quatro personas, em 1280×720 e em 360×740, e falha se achar uma caixa com o conteúdo passando da borda, a página rolando de lado, a marca por cima das abas ou do relógio, ou um nome de aba cortado na barra de baixo.

### Alto contraste

Três escolhas em Ajustes › Aparência (Alto contraste), ou na paleta (`Ctrl+K`: "alto contraste"):

| Escolha | O que faz |
| --- | --- |
| Automático (o de fábrica) | Liga sozinho quando o sistema pede mais contraste (`prefers-contrast: more`: "Aumentar contraste" do macOS, do iOS e do Android; ou um tema de contraste do Windows, que aparece como `forced-colors`). Se a opção do sistema mudar com o HUD aberto, o HUD acompanha na hora. |
| Ligado | Sempre em alto contraste. |
| Desligado | Nunca, mesmo que o sistema peça. A escolha da pessoa vale mais que a do sistema. |

O que muda (tudo em `web/src/styles/contrast.css`, ligado por `data-contrast="high"` no `<html>`):

- **Texto**: branco com o tom da persona, e os níveis apagados (`--text-dim`, `--text-faint`) sobem para 96% e 86%. Sobre o painel, o texto principal passa de 12:1 e os dois apagados de 7:1 (o nível AAA).
- **Painéis opacos**: sem o degradê translúcido, sem o desfoque do fundo e sem o pontilhado. O núcleo 3D e o globo não aparecem por trás do texto, e fora do Painel o núcleo fica a 10%. Chips e a placa do protocolo ganham fundo sólido, e a legenda e o texto da linha de status, um fundo escuro quase opaco.
- **Bordas**: a cor cheia da persona, em painéis, cabeçalhos, botões e campos. Os cantos de moldura ficam acesos.
- **Sem o que atrapalha**: scanlines, a varredura que desce a tela, a luz nas bordas, a moldura que respira (F.R.I.D.A.Y.), o traço de energia nos cabeçalhos, halos em texto e brilho nos pontos de estado e nas caixas. Nada pisca (o selo SIMULAÇÃO e o ponto "ocupado" ficam parados).
- **Seleção**: a opção marcada (persona, tamanho, tipo de consulta) vira um bloco cheio com letra escura, e a aba aberta ganha fundo mais forte. Controles desativados ficam a 70% em vez de 45%.

O que não muda: a cor primária e a de acento de cada persona, o formato dos painéis (placas de cantos cortados do Mark III, vidro arredondado da F.R.I.D.A.Y., traço fino do Stealth), as fontes e o núcleo 3D. Cada persona tem o próprio fundo opaco e o próprio tom de branco, então o Mark III continua âmbar e a F.R.I.D.A.Y. continua lilás. O estado também nunca depende só da cor: ✓, ! e ✕ nos veredictos, e texto nos chips.

### Legenda ao vivo

A fala do Jarvis aparece palavra por palavra embaixo do núcleo e some alguns segundos depois.

### Modo cinema

Esconde os painéis, aproxima o núcleo e aumenta a legenda. Liga pelo botão ao lado do dock, pela tecla `F` ou falando "modo cinema". As notificações continuam aparecendo.

### Modo ambiente

Depois de 3 minutos sem link e sem mexer no mouse ou no teclado, o HUD vira um relógio grande com o clima da `JARVIS_HOME_CITY` e a próxima reunião (com a [agenda](agenda.md) ligada). O núcleo fica em baixa energia e o relógio anda alguns pixels por minuto para não marcar a tela. Qualquer movimento, um "Jarvis" ou um aviso trazem o HUD de volta.

### Notificações

Avisos proativos, timers que acabaram, reunião chegando, rotina agendada e troca de modelo entram pela direita. Os críticos ficam até você clicar.

### Gráficos nos painéis

O painel do clima mostra a temperatura das próximas 24 horas (passe o mouse para ver cada hora e a chance de chuva). O diagnóstico atualiza CPU e RAM ao vivo enquanto está aberto. A agenda desenha o dia em blocos, com um marcador de agora.

### Painel de saúde

O painel Saúde (SAU-40) guarda o histórico do tempo de resposta, das ativações por palavra, das falhas de ferramentas e das pausas de modelo, com sugestões do que ajustar no `.env`. Detalhes em [saude.md](saude.md).

### Painéis arrastáveis

No computador, os quatro painéis do Painel (Briefing, Projeções, Transcrição e Registro) mudam de coluna ou de posição arrastando pelo cabeçalho. "Restaurar painéis" volta ao layout de fábrica. No celular os painéis não se arrastam, de propósito: a ordem é fixa, com a conversa logo abaixo do núcleo.

### Qualidade da cena

Automática (padrão) mede os quadros por segundo e corta partículas e efeitos quando o PC fica lento por uns 8 segundos seguidos. Depois de uns 40 segundos com folga, ela tenta voltar. Cada troca aparece no Registro, porque o canvas muda de resolução e fica um quadro em branco. Alta, Média e Economia fixam o nível. O painel mostra o nível em uso e os fps.

### Som do reator

Um zumbido baixo que cresce com a voz do Jarvis enquanto o link está aberto. Vem desligado e segue o volume dos sons da interface.

### Microfone

O seletor de microfone e os medidores de voz ficam no painel Áudio. Se o microfone escolhido não entregar som, o Briefing e o painel Sistema mostram o aviso com um atalho para lá.

## Acessibilidade

Além do tamanho do texto e do alto contraste, o HUD segue estas regras (e `web/e2e/acessibilidade.e2e.ts` confere):

- **Foco do teclado visível em todo lugar**: contorno de 2 px na cor da persona em botões, campos, caixas de marcar, abas e links. Os campos de texto que antes só trocavam a cor da borda ao focar (linha de comando, Nova tarefa, consulta do Olho de Deus, senha, nome do aparelho) ganharam o contorno. Os botões de forma recortada (`clip-path`: o dock, as abas, os chips, a câmera) levam o contorno por dentro da borda e fundo mais forte, porque por fora o recorte o cortaria.
- **Pular para o conteúdo**: o primeiro `Tab` da página é um link que só aparece com o foco. `Enter` leva o foco ao primeiro painel da área aberta; o `Tab` seguinte cai no primeiro controle dele, sem passar de novo pelas abas e pelos chips.
- **Ordem da tabulação**: topo (abas, chips), o conteúdo da área (coluna da esquerda, depois a do meio, depois a da direita, cada uma de cima para baixo) e o dock. Não há `tabindex` positivo. No Dia a dia: Tarefas (caixas de marcar, apagar, campos), Foco, Cotações e Rede. No Olho de Deus: Consulta, Senha, Aparelhos e Resultados.
- **Nome em todo controle**: botões só de ícone têm `aria-label`, e os que se repetem dizem de quem são ("Esquecer Celular da Ana", "Salvar o nome de TV da sala", "192.168.0.50 é meu", "Apagar Fechar o relatório"). Todo campo tem rótulo.
- **Avisos ao leitor de tela** (`aria-live`, sempre no modo educado):
  - Dia a dia: o resumo das tarefas ("2 abertas · 1 atrasada") anuncia ao marcar, apagar ou adicionar; o Foco anuncia só a troca de bloco ("Bloco de foco 2 de 4", "Pausa 2 de 4", "parado"). A contagem que anda a cada segundo não é anunciada.
  - Olho de Deus: "Consultando…" enquanto espera, o tipo reconhecido, o total de resultados da sessão, o veredito da senha vazada e os erros (`role="alert"`).
  - Topo: o estado do link e do microfone ("Link ativo, microfone aberto.") em voz baixa, sem aparecer na tela.
  - A transcrição, o registro, os avisos e o estado do dock já eram `aria-live`.
- **Movimento reduzido**: com `prefers-reduced-motion`, as animações e as transições encurtam para quase zero (já era assim).

## Atalhos de teclado

| Tecla | Ação |
| --- | --- |
| `Espaço` | Inicia o link (ou diga "Jarvis", com a [palavra de ativação](voz.md#palavra-de-ativação)) |
| `Ctrl+K` | Paleta de comandos |
| `1` a `5` | Painel, Dia a dia, Olho de Deus, Sistema e Ajustes |
| `M` | Silencia ou ativa o microfone |
| `/` | Vai para a linha de comando de texto |
| `F` | Modo cinema (de novo para voltar) |
| `Esc` | Sai do painel ampliado, depois do modo cinema, depois volta ao Painel, depois limpa as projeções |

## O que cada persona muda

A persona escolhida fica no servidor, em `persona.json` (fora do git). O agente começa cada conversa nela, e o PC e o celular mostram a mesma. Trocada no meio da conversa, por clique ou por voz, a persona e a voz mudam na hora: o agente espera a conversa ficar quieta por um instante, para não cortar a confirmação, e a nova persona se apresenta. A holografia se rematerializa enquanto as peças do núcleo trocam.

| | J.A.R.V.I.S. | Mark III | F.R.I.D.A.Y. | Stealth |
| --- | --- | --- | --- | --- |
| Quem responde | O mordomo britânico, que chama você de "senhor" e tem humor seco | O Jarvis dentro da armadura, com respostas curtas de relatório ("sistemas nominais") | A F.R.I.D.A.Y., direta, calorosa e irreverente, que chama você de "chefe" | O Jarvis em modo discreto: uma frase, sem piadas |
| Voz padrão | Charon (ou a `JARVIS_VOICE`) | Orus | Kore, feminina | Enceladus, sussurrada |
| Núcleo 3D | Treliça de icosaedros, anéis clássicos e espectro em barras | Reator arc com 10 células e bobinas, mira tática que gira aos saltos, espectro em blocos e faíscas | Giroscópio de três anéis, plasma líquido, arcos suaves e espectro em contas de luz | Um anel fino, sem partículas, sem feixe e com pouco brilho |
| Painéis | Recorte em dois cantos e fonte Orbitron | Placas de armadura com os quatro cantos cortados, fonte Teko, moldura de mira e scanlines mais fortes | Vidro arredondado, fonte Exo 2, moldura que respira e sem scanlines | Traço fino, fonte mono, sem halos e sem scanlines |
| Sons | Senoidais | Mais graves e mecânicos | Mais agudos e leves | Baixinhos |

"Jarvis" acorda qualquer persona. Com o modelo da "Friday" treinado, dizer "Friday" abre o link já como F.R.I.D.A.Y. (veja [voz.md](voz.md#uma-palavra-por-persona)). "Troca sua voz para X" vale para a persona ativa (veja [voz.md](voz.md#voz-e-persona)). Com a OpenAI, a persona muda e a voz continua a da `OPENAI_VOICE`. As personas estão em `personas.py` (agente) e em `web/src/lib/themes.ts` e `web/src/styles/personas.css` (HUD).

## Núcleo 3D

Quando o Gemini está pensando, três arcos de varredura giram em volta do plasma e quatro "bits" orbitam o núcleo. Enquanto uma ferramenta roda, aparecem um anel de marcações girando e um giroscópio duplo. No fim dela, uma onda de choque sai do núcleo, vermelha se a ferramenta falhou.

## Tamanho do pacote

O HUD baixa só o que a tela precisa. O `npm run build` gera um pacote principal pequeno e vários pedaços que o navegador pede na hora de usar (tamanhos em kB, sem e com gzip):

| Pedaço | Quando é baixado | kB | gzip |
| --- | --- | --- | --- |
| `index` (React, painéis do Painel, estado) | sempre, na abertura | 365 | 118 |
| `Scene` (Three.js e efeitos) | na abertura, enquanto o boot roda | 1052 | 281 |
| `landDots` (mapa-múndi do globo: `d3-geo`, `world-atlas`) | com a cena | 77 | 31 |
| `motionFeatures` (layout e gestos do `motion`) | logo depois da primeira pintura | 95 | 32 |
| `CommandPalette` (Ctrl+K) | logo depois da abertura, fechada: a primeira letra digitada não se perde | 4 | 2 |
| `DayView`, `EyeView`, `SystemView`, `SettingsView` | na primeira vez que a área é aberta (tecla ou aba) | 2 a 14 cada | 1 a 5 |
| `CardBodies` (o corpo de cada painel projetado) | quando o link abre ou uma ferramenta começa a rodar | 40 | 12 |
| `AmbientMode` | na primeira vez que o modo ambiente entra | 2 | 1 |
| `LiveSession` (`livekit-client` e `@livekit/components-react`) | só quando `/api/status` diz que o LiveKit está configurado | 631 | 167 |

Antes desta mudança o pacote principal tinha 1291 kB (386 kB com gzip), com o LiveKit, o `motion` inteiro, as quatro áreas, a paleta e os painéis projetados dentro dele, e o `chunkSizeWarningLimit` estava em 1800 para esconder o aviso. Agora:

| | Antes | Depois |
| --- | --- | --- |
| Pacote principal (`index`) | 1291 kB · 386 kB gzip | 365 kB · 118 kB gzip |
| JavaScript baixado na abertura (com a cena) | 2343 kB · 667 kB gzip | 1635 kB · 481 kB gzip |
| Maior pedaço | `index`, 1291 kB | `Scene`, 1052 kB |
| `chunkSizeWarningLimit` | 1800 | 1100 |

O tamanho do texto, o alto contraste e a revisão de acessibilidade somaram uns 2 kB ao `index` (as preferências e o link "Pular para o conteúdo") e uns 3 kB ao CSS (`a11y.css` e `contrast.css`, que ficam no CSS principal, de 105 kB). O `Scene` é o único pedaço acima de 500 kB que sobra na abertura (é o Three.js, que a cena precisa inteiro), por isso o limite é 1100 e não menos: o aviso do `vite build` volta se alguma coisa passar disso. O `LiveSession` (631 kB) vem fora do caminho do boot, mas com o LiveKit configurado ele é baixado em paralelo assim que o status chega; sem LiveKit, ou antes do status, o navegador nem o pede.

O que mudou:

- As áreas Dia a dia, Olho de Deus, Sistema e Ajustes, a paleta, o modo ambiente, os painéis projetados e o LiveKit são `lazy` (`App.tsx`). Cada área é um arquivo próprio (`SystemView.tsx` e `SettingsView.tsx` saíram do antigo `Workspaces.tsx`, e a moldura ficou em `Workspace.tsx`).
- Ao abrir uma área pela primeira vez, a anterior continua na tela até o código chegar e só então a nova entra (uma transição do React: `useShownView`). Nada de tela vazia no meio; `data-pending` no `main.app` marca a espera e o cursor vira "carregando". Numa rede lenta, como o celular no Wi-Fi, a área só troca quando termina de baixar.
- `lib/audio.ts` ganhou o próprio analisador de áudio (Web Audio) no lugar do `createAudioAnalyser` do LiveKit. Era o único motivo de o `livekit-client` entrar no pacote principal e no da cena.
- O estado do link (`LiveJarvis`, `OFFLINE_LIVE`) mora em `hooks/liveState.ts`, separado do hook que puxa o LiveKit.
- O `motion` virou `LazyMotion`: os componentes `m.*` pintam o estado inicial e os recursos de animação (`domMax`, que inclui o `layout` usado nos avisos e nos painéis) chegam num pedaço à parte.
- Os atalhos de teclado do `App.tsx` usam um único ouvinte de `keydown` (antes ele era religado a cada renderização, e uma tecla apertada logo depois de trocar de área se perdia).

O que foi conferido e ficou como está: o `n8ao`, que o `@react-three/postprocessing` importa, só pesava 9 kB no pacote (o resto já era descartado); `d3-geo`, `topojson-client` e `world-atlas` vêm com o globo 3D e somam 31 kB com gzip; tirar qualquer um mudaria o visual do mapa.

O teste `a área Painel abre sem baixar o código das outras áreas` (`web/e2e/hud.e2e.ts`) garante que nenhum pedaço das áreas, dos painéis projetados nem do LiveKit é pedido na abertura, e que cada área só é baixada quando aberta. Outro teste atrasa o `SystemView` de propósito, no computador e no celular, e confere que o Painel continua inteiro até o código chegar.

## Sons da interface

O HUD gera os sons por código, com Web Audio e sem arquivos de terceiros: link abrindo e fechando, ferramenta começando e terminando, código de confirmação aceito, erro e timer acabando. Em Ajustes, "Sons da interface" liga e desliga, ajusta o volume e toca um teste. O bipe da palavra de ativação segue a mesma configuração, e quando o silêncio encerra o link toca um som só.

Os tons ficam em `web/src/lib/sounds.ts` (`SOUND_CUES`).

## Modo simulação

Sem LiveKit configurado, o botão Simulação roda uma conversa roteirizada com áudio sintético, para você ver todos os estados, painéis, animações e sons. Os dados desse modo são fictícios e o HUD mostra o selo "SIMULAÇÃO". Para abrir só o HUD, use `python jarvis.py --no-agent`.
