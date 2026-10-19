# HUD

O HUD roda no navegador (React com Three.js) e é servido pelo `server.py` em `http://127.0.0.1:8000`.

## O que aparece na tela

No centro fica o núcleo de plasma, feito com shader, rodeado por anéis com marcações, órbitas giroscópicas, um disco de partículas e a grade holográfica no piso, tudo com bloom. Ele reage em tempo real ao áudio do Jarvis e do seu microfone e muda de cor com o estado: ouvindo, processando ou respondendo. Ao processar, o HUD inteiro fica âmbar. Numa falha, vermelho.

Quando o Jarvis usa uma ferramenta, um painel holográfico se projeta nas colunas laterais: clima com previsão de 5 dias e o globo girando até a cidade, resultados de pesquisa, notícias, relógio mundial, diagnóstico do PC, timers com contagem regressiva, notas, rascunhos de email e os painéis de cada protocolo. Uma placa sobre o núcleo mostra o protocolo em execução (código, nome e alvo) e depois o resultado.

Enquanto ele pensa ou busca algo na internet, o núcleo vira um globo que desenha arcos da sua cidade até os serviços consultados. Nas pesquisas o globo cresce, os anéis recuam e cada destino ganha um rótulo com a cidade e o serviço.

Também tem a transcrição ao vivo da conversa (com hora), a linha de comando para mandar texto em vez de falar, o registro de atividades em linha do tempo, o radar no piso e o feixe de luz do projetor. O boot mostra o anel do reator se completando e os painéis entram em cascata depois dele.

## Ajustes

Fica no botão Ajustes do painel Sistema. Tudo que você muda ali é salvo no navegador.

### Temas

J.A.R.V.I.S. (ciano e âmbar, o padrão), Mark III (dourado e vermelho), F.R.I.D.A.Y. (violeta e rosa) e Stealth (prata e verde-água). O tema muda o HUD e a cena 3D. O estado de processando ganha um tom próprio de cada tema, e a falha continua vermelha em todos. Também dá para trocar por voz: "Jarvis, muda o tema para vermelho", "deixa roxo", "volta ao normal".

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

### Painéis arrastáveis

No computador, arraste um painel pelo cabeçalho para a outra coluna ou outra posição. "Restaurar painéis" volta ao layout de fábrica. No celular os painéis não se arrastam, de propósito.

### Qualidade da cena

Automática (padrão) mede os quadros por segundo e corta partículas e efeitos quando o PC não acompanha, voltando quando sobra fôlego. Alta, Média e Economia fixam o nível. O painel mostra o nível em uso e os fps.

### Som do reator

Um zumbido baixo que cresce com a voz do Jarvis enquanto o link está aberto. Vem desligado e segue o volume dos sons da interface.

### Microfone

O seletor de microfone e o medidor "Entrada de voz" também ficam em Ajustes. Se o microfone escolhido não entregar som, os ajustes abrem sozinhos junto com o aviso. A escolha de deixar os ajustes abertos ou fechados também fica salva.

## Atalhos de teclado

| Tecla | Ação |
| --- | --- |
| `Espaço` | Inicia o link (ou diga "Jarvis", com a [palavra de ativação](voz.md#palavra-de-ativação)) |
| `M` | Silencia ou ativa o microfone |
| `/` | Vai para a linha de comando de texto |
| `F` | Modo cinema (de novo para voltar) |
| `Esc` | Sai do painel ampliado, depois do modo cinema, depois limpa os painéis |

## Núcleo 3D

Quando o Gemini está pensando, três arcos de varredura giram em volta do plasma e quatro "bits" orbitam o núcleo. Enquanto uma ferramenta roda, aparecem um anel de marcações girando e um giroscópio duplo. No fim dela, uma onda de choque sai do núcleo, vermelha se a ferramenta falhou.

## Sons da interface

O HUD gera os sons por código, com Web Audio e sem arquivos de terceiros: link abrindo e fechando, ferramenta começando e terminando, código de confirmação aceito, erro e timer acabando. Em Ajustes, "Sons da interface" liga e desliga, ajusta o volume e toca um teste. O bipe da palavra de ativação segue a mesma configuração, e quando o silêncio encerra o link toca um som só.

Os tons ficam em `web/src/lib/sounds.ts` (`SOUND_CUES`).

## Modo simulação

Sem LiveKit configurado, o botão Simulação roda uma conversa roteirizada com áudio sintético, para você ver todos os estados, painéis, animações e sons. Os dados desse modo são fictícios e o HUD mostra o selo "SIMULAÇÃO". Para abrir só o HUD, use `python jarvis.py --no-agent`.
