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
| Olho de Deus | `2` | Consultas em fontes públicas: um campo que reconhece IP, domínio, link, CNPJ, CEP, DDD, email ou usuário, a checagem de senha vazada e os resultados da sessão ([olho-de-deus.md](olho-de-deus.md)) |
| Sistema | `3` | Estado do link e do modelo, tempo de resposta, voz, ativação por voz, presença, o painel de Saúde, o do Celular, os Gestos e a lista de Protocolos com o que está ligado no `.env` |
| Ajustes | `4` | Aparência (persona, qualidade da cena, legenda, modo ambiente, som do reator), Áudio (microfone, medidores e sons da interface) e a lista de atalhos |

Fora do Painel o núcleo recua para o fundo e os painéis da área ocupam a tela. `Esc` volta ao Painel.

### Briefing

O primeiro painel do Painel junta o que importa agora: a saudação pela hora, o clima da `JARVIS_HOME_CITY`, a próxima reunião (com a [agenda](agenda.md) ligada), o que pede atenção (configuração pendente, servidor fora do ar, microfone sem sinal) e três frases de exemplo dos protocolos ligados, que mudam a cada dia. Com o link aberto, clicar numa frase manda o pedido por texto.

Quando o Jarvis projeta um painel, o Briefing encolhe para uma linha e deixa o espaço para as projeções. A setinha do cabeçalho abre e recolhe na mão.

### Projeções

Quando o Jarvis usa uma ferramenta, um painel holográfico se projeta na coluna das Projeções: clima com previsão de 5 dias e o globo girando até a cidade, resultados de pesquisa, notícias, relógio mundial, diagnóstico do PC, timers com contagem regressiva, notas, rascunhos de email e os painéis de cada protocolo. Uma placa sobre o núcleo mostra o protocolo em execução (código, nome e alvo) e depois o resultado.

Enquanto ele pensa ou busca algo na internet, o núcleo vira um globo que desenha arcos da sua cidade até os serviços consultados. Nas pesquisas o globo cresce, os anéis recuam e cada destino ganha um rótulo com a cidade e o serviço.

Também tem a transcrição ao vivo da conversa (com hora), a linha de comando para mandar texto em vez de falar, o registro de atividades em linha do tempo, o radar no piso e o feixe de luz do projetor. O boot mostra o anel do reator se completando e os painéis entram em cascata depois dele.

### Paleta de comandos

`Ctrl+K` (ou a lupa nas abas e no dock) abre uma busca com tudo o que o HUD faz por clique: ir para uma área, iniciar e encerrar o link, microfone, simulação, as quatro personas, modo cinema, legenda, modo ambiente, qualidade da cena e restaurar os painéis. Os protocolos ligados também aparecem, cada um com uma frase de exemplo que vai por texto ao Jarvis. Digitar um IP, domínio, link, CNPJ, CEP ou email oferece a consulta no Olho de Deus como primeira opção. Com o link aberto, o que você digitar e não for um comando vira "Enviar ao Jarvis". Setas navegam, `Enter` executa e `Esc` fecha. A busca ignora acentos.

## Ajustes

É a última área (tecla `4`, ou o botão Ajustes do painel Sistema). Tudo que você muda ali é salvo no navegador.

### Personas

J.A.R.V.I.S. (o padrão), Mark III, F.R.I.D.A.Y. e Stealth. Cada persona muda a identidade inteira, não só as cores: quem responde e com que voz, o núcleo 3D, o formato dos painéis, as fontes, o boot e os sons. Detalhes em [O que cada persona muda](#o-que-cada-persona-muda), mais abaixo. Também dá para trocar por voz: "Jarvis, chama a Friday", "modo Mark III", "modo discreto", "volta ao normal", "deixa roxo".

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

## Atalhos de teclado

| Tecla | Ação |
| --- | --- |
| `Espaço` | Inicia o link (ou diga "Jarvis", com a [palavra de ativação](voz.md#palavra-de-ativação)) |
| `Ctrl+K` | Paleta de comandos |
| `1` `2` `3` `4` | Painel, Olho de Deus, Sistema e Ajustes |
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

## Sons da interface

O HUD gera os sons por código, com Web Audio e sem arquivos de terceiros: link abrindo e fechando, ferramenta começando e terminando, código de confirmação aceito, erro e timer acabando. Em Ajustes, "Sons da interface" liga e desliga, ajusta o volume e toca um teste. O bipe da palavra de ativação segue a mesma configuração, e quando o silêncio encerra o link toca um som só.

Os tons ficam em `web/src/lib/sounds.ts` (`SOUND_CUES`).

## Modo simulação

Sem LiveKit configurado, o botão Simulação roda uma conversa roteirizada com áudio sintético, para você ver todos os estados, painéis, animações e sons. Os dados desse modo são fictícios e o HUD mostra o selo "SIMULAÇÃO". Para abrir só o HUD, use `python jarvis.py --no-agent`.
