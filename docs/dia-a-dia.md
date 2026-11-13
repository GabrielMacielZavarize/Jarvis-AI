# Dia a dia

O que se usa todo dia sem pensar: tarefas e notas, o briefing, o foco, as cotações e o teste da internet. Tudo funciona por voz e pela área Dia a dia do HUD (tecla `2`); o foco também conversa com a presença, os avisos e a bandeja. Um interruptor só liga e desliga o conjunto: `JARVIS_ENABLE_DAY` (vem ligado).

## Como o Jarvis escolhe

Alguns pedidos se parecem e vão para ferramentas diferentes. O prompt do Jarvis (só com o Dia a dia ligado) desempata assim:

| Você diz | Vira |
| --- | --- |
| "Anota aí: ideia do painel de consumo." | Nota (`add_note`) |
| "Tenho que fechar o relatório até sexta." | Tarefa com prazo de um dia (`add_task`) |
| "Lembra que eu prefiro lo-fi pra programar." / "Anota que eu sou alérgico a dipirona." | Fato sobre você (`remember`, com a memória ligada) |
| "Me lembra às 15h de ligar pro contador." | Aviso numa hora marcada (`set_reminder`, com os [avisos](avisos.md) ligados), mesmo que comece com "tenho que" |
| "Timer de 5 minutos." | Contagem só desta conversa (`set_timer`) |
| "Começa um foco de 25 minutos." / "Um pomodoro." | Sessão de foco (`focus_session`) |
| "Modo foco." | A rotina "modo foco", se as rotinas estiverem ligadas; sem elas, a sessão de foco |
| "Como está o meu dia?" | Briefing (`daily_briefing`) |
| "O que eu tenho hoje?" | A agenda, se a [agenda](agenda.md) estiver ligada; sem ela, o briefing |
| "Bom dia, Jarvis." | A rotina "bom dia", que usa o briefing como um dos passos |
| "10 milhas em quilômetros." | Conversão de unidade, conta local, sem internet |

Tarefa com hora marcada e aviso pedido é um lembrete, não uma tarefa: o prazo da tarefa é sempre um dia, sem hora. Só vira as duas coisas se você pedir as duas. As ferramentas de tarefas e notas ficam sempre com o Jarvis, mesmo com as [ferramentas sob demanda](ferramentas-sob-demanda.md); briefing, foco, cotações e teste de rede vêm no grupo `dia`.

## Tarefas e notas (TAR-43)

Uma tarefa tem um texto, um prazo opcional (um dia, sem hora) e fica aberta ou feita. Uma nota é só um texto guardado. Aviso com hora marcada é outra coisa: são os lembretes do PRO-28 ([avisos.md](avisos.md)).

| Você diz | O que acontece |
| --- | --- |
| "Tenho que fechar o relatório até sexta." | Tarefa com prazo na próxima sexta |
| "Põe na lista: comprar café." | Tarefa sem prazo |
| "Anota aí: ideia do painel de consumo." | Nota |
| "O que falta hoje?" / "Minhas notas." | Lê a lista e abre o painel Tarefas |
| "Já fiz o relatório." / "Risca a segunda." | Marca como feita, pelas palavras ou pela posição na lista lida |
| "Tira o dentista da lista." / "Apaga a nota do livro." | Apaga sem marcar como feita |

Prazos aceitos: hoje, amanhã, depois de amanhã, um dia da semana ("sexta" dito numa sexta é a da semana seguinte), "dia 20", "20/11" e "2026-11-20". As tarefas são lidas com as de prazo primeiro, da mais próxima para a mais distante, e as atrasadas aparecem marcadas em vermelho.

No HUD, o painel Tarefas marca com um clique, apaga no X e tem um campo para escrever tarefa e nota. O Briefing do Painel mostra as quatro primeiras abertas.

### Aviso de manhã

Com os [avisos proativos](avisos.md#tarefas-do-dia) ligados (`JARVIS_PROACTIVE=true`), o Jarvis avisa sozinho, uma vez por dia, no primeiro momento útil da manhã (entre 5h e 12h, fora do horário de silêncio e com você na frente do PC se a presença estiver ligada): "2 tarefas atrasadas e 1 para hoje: ...". Sem tarefa atrasada nem para hoje, ele fica quieto, e nunca repete no mesmo dia. "Para de me avisar sobre tarefas" silencia o aviso. Com `JARVIS_ENABLE_DAY=false` ele não existe.

O que vale saber:

- Tudo fica em `tarefas.json`, na pasta do projeto e fora do git. Nada vai para a nuvem.
- Repetir uma tarefa que já está aberta não duplica: só atualiza o prazo, se você disse um.
- Tarefas feitas saem do arquivo depois de 14 dias.
- Um texto com cara de senha ou token ("a senha do banco é...", "token: ...") é recusado: o arquivo é texto puro.
- Se o arquivo estragar, ele é guardado como `tarefas.corrompido-<data>.json` e a lista recomeça.

## Briefing do dia (BRF-46)

"Como está o meu dia?", "me dá o resumo do dia". O Jarvis fala e projeta num painel só:

- o clima da `JARVIS_HOME_CITY`;
- a próxima reunião, com a [agenda](agenda.md) ligada;
- as tarefas abertas, quantas estão atrasadas e quantas são para hoje;
- os lembretes das próximas 24 horas, com os [avisos](avisos.md) ligados;
- dólar, euro e bitcoin;
- até quatro manchetes.

O mesmo resumo alimenta o painel Briefing do Painel, que se atualiza a cada 5 minutos. Quem monta é o servidor do HUD (`/api/briefing`), que guarda o clima por 10 minutos, as cotações por 10 e as manchetes por 30. A parte que falhar fica de fora e o resto aparece.

`JARVIS_BRIEFING_NEWS` escolhe o assunto das manchetes (o padrão é "principais notícias do Brasil hoje"). Vazio ou `false` tira as manchetes, e aí o briefing não faz essa busca.

### No "bom dia"

A rotina de fábrica "bom dia" ([memoria-e-rotinas.md](memoria-e-rotinas.md#rotinas)) usa este mesmo briefing: o passo `briefing` busca o resumo no servidor do HUD, abre o painel Briefing e entrega o texto para o Jarvis falar. Ele substitui os passos separados de clima, notícias e lembretes; o cumprimento, o layout "trabalho" e a música continuam.

Qualquer rotina sua pode ter o passo: "cria uma rotina cedo que dá o briefing e abre o Notion". Duas situações especiais:

- Com o HUD fora do ar, o passo falha com uma mensagem clara e o resto da rotina segue.
- Com `JARVIS_ENABLE_DAY=false`, o passo cai no clima, nas notícias e nos lembretes de antes, e avisa que o briefing está desligado.

Quem já tem um `rotinas.json` mantém o "bom dia" que salvou; a troca só vale para o arquivo novo ou quando você pedir.

## Foco (FOC-47)

Blocos de trabalho com pausas, no estilo Pomodoro: "começa um foco de 25 minutos", "foco de 50 com pausa de 10, três blocos", "quanto falta do foco?", "pula esse bloco", "encerra o foco".

A contagem mora no **servidor do HUD** (`focus.py`), não na aba do navegador nem no agente de voz. Por isso ela anda com o HUD fechado, depois que o link fecha por silêncio e até depois de um "Reiniciar o Jarvis" da bandeja: o estado fica em memória e em `foco.json`, na pasta do projeto e fora do git. O arquivo é pequeno e não guarda nada além dos tempos e de onde a sessão está. Se o Jarvis ficou desligado por mais de um bloco, ao subir ele passa pelos blocos que venceram e avisa só a última troca.

O HUD apenas mostra a sessão (o anel no painel, o chip na barra do topo, em qualquer área, que ao clique abre o Dia a dia) e manda os comandos do painel e da paleta (`Ctrl+K`, "Começar o foco" usa os tempos do painel). Recarregar a página não zera nada. Depois do último bloco de foco não há pausa: a sessão acaba.

Limites: foco de 1 a 180 minutos, pausa de 1 a 60 e de 1 a 12 blocos.

### Quem avisa a troca de bloco

A cada troca ("Hora da pausa", "De volta ao foco", "Sessão de foco concluída") o servidor avisa pelo mesmo caminho dos [avisos proativos](avisos.md#durante-o-foco), com o assunto `foco` e prioridade normal:

| Situação | O que acontece |
| --- | --- |
| Aba do HUD aberta | Som de timer, notificação e registro na tela |
| Link aberto | Além disso, o Jarvis fala a troca |
| Sem aba, com o ícone da [bandeja](bandeja.md#avisos-do-jarvis-na-bandeja) | Notificação do Windows |
| Sem aba e sem a bandeja | Fica no registro do servidor e na tela da próxima aba que abrir. Não abre o navegador nem acorda o Jarvis |

Escolhemos a prioridade normal de propósito: quem fecha o HUD para trabalhar não quer um navegador pulando a cada 25 minutos, então o aviso não abre o link como um lembrete faz. "Para de me avisar sobre o foco" silencia a voz (o HUD e a bandeja continuam mostrando).

Pular o bloco pelo botão ou por voz não gera esse aviso: quem pediu já sabe. O HUD toca o som e mostra a notificação.

### Com a presença ligada

Com a [presença](camera-e-presenca.md) ligada (`JARVIS_PRESENCE=true`, com a câmera), sair da frente do PC durante um **bloco de foco** pausa a contagem:

- A presença marca "ausente" depois de uns 20 segundos sem rosto, teclado nem mouse. Uma ausência de menos de 1 minuto (pegar um café, atender a porta) não pausa nada. Passou disso, a contagem para e **o tempo da ausência fica de fora**, inclusive o minuto de tolerância (só os 20 segundos que a presença leva para notar que você saiu continuam contando).
- O anel e o chip do topo mostram "parado", e o `focus_session` diz "pausado porque você saiu".
- Ao voltar, a contagem retoma e o Jarvis avisa quanto falta: "Foco retomado. Bem-vindo de volta. Faltam 14 min do bloco 2 de 4." Esse aviso segue o caminho da tabela acima.
- Se a presença for desligada no meio da pausa, a contagem volta sozinha, sem aviso.
- Na **pausa** (o descanso) a ausência é esperada e não pausa nada. Se a pausa acabar com você ainda longe, o próximo bloco começa e é ele que fica parado até você voltar.
- Presença desligada, câmera desligada ou estado ainda "desconhecido": nada muda, a contagem é só relógio.

### Avisos esperam o bloco

Enquanto um bloco de foco corre (mesmo parado pela ausência), os avisos proativos que **não são críticos** esperam o fim do bloco: download concluído, CPU alta, disco, tarefas, lembrete comum e a bateria em 20%. Nem a notificação aparece. Quando o bloco acaba (a pausa começa, a sessão termina ou você encerra o foco), eles saem juntos, pelo caminho de sempre, com "(chegou às 14:02, durante o foco)" no fim. Continuam furando o foco: a bateria em 10%, o lembrete marcado como urgente e a troca de bloco do próprio foco. Detalhes em [avisos.md](avisos.md#durante-o-foco).

A rotina "modo foco" ([memoria-e-rotinas.md](memoria-e-rotinas.md)) continua existindo e faz outra coisa: minimiza as janelas, baixa o volume e põe um timer. Dito sozinho, "modo foco" é a rotina; "foco de 25 minutos", "pomodoro" e "bloco de foco" são a sessão. Quem esconde os painéis é o "modo cinema" ([hud.md](hud.md)): "modo foco" só faz isso se não existir a rotina nem a sessão de foco.

## Cotações e conversões (COT-44)

- "Quanto está o dólar?", "e o bitcoin?", "cotação do euro e da libra."
- "Quanto dá 150 dólares em reais?", "100 reais em euro."
- "10 milhas em quilômetros", "100 fahrenheit em celsius", "2 quilos em libras", "90 minutos em horas."

As cotações vêm da AwesomeAPI (pública, sem chave) e ficam um minuto em memória. Moedas: real, dólar, euro, libra, peso argentino, iene, dólar canadense e australiano, franco suíço, yuan, bitcoin e ethereum. Entre duas moedas estrangeiras a conversão passa pelo real.

Conversão de unidade é conta local, sem rede: comprimento, peso, volume, temperatura, velocidade, tempo, dados (1 GB = 1024 MB) e área. "Libra" sozinha é a moeda; ao lado de um peso ("libras em quilos") é a unidade.

## Velocidade da internet (RED-45)

"Como está a minha internet?", "testa a velocidade". Mede a latência (o tempo de abrir uma conexão com 1.1.1.1 e 8.8.8.8), o download e o upload nos servidores de teste da Cloudflare, e diz se está boa, razoável ou lenta. O painel Rede guarda as últimas 60 medições em `rede.json` (fora do git) e desenha a evolução do download.

- O teste gasta banda de verdade: até 25 MB de download e 4 MB de upload, com no máximo 7 segundos de download. Serve para saber se a rede está boa, não para medir o último megabit do plano.
- Um teste por vez e, no mínimo, 20 segundos entre dois.
- Sem internet ele para na latência e não tenta o resto.
- O botão "Medir agora" só aparece no próprio PC. Um celular pareado vê o histórico, mas não dispara o teste.

## Configuração

| Variável | Padrão | O que faz |
| --- | --- | --- |
| `JARVIS_ENABLE_DAY` | `true` | Liga tarefas, notas, briefing, foco, cotações e teste de rede. `false` tira as ferramentas de voz, as rotas `/api/tasks`, `/api/focus` e `/api/network/test`, a contagem do foco e o aviso de tarefas da manhã |
| `JARVIS_BRIEFING_NEWS` | `principais notícias do Brasil hoje` | Assunto das manchetes do briefing. Vazio ou `false`: sem manchetes |

## Arquivos

- `tasks.py`, `quotes.py`, `netcheck.py` e `briefing.py` (que também tem a ferramenta do foco). O foco em si é o `focus.py`: a sessão, o `foco.json` e as rotas `/api/focus`.
- `web/src/lib/day.ts`, `web/src/lib/focus.ts` e `web/src/hooks/useFocusSync.ts`; `web/src/components/DayView.tsx` e `web/src/components/cards/DayCards.tsx`.
- Testes: `tests/test_day.py`, `tests/test_focus.py` (relógio injetável), `web/src/lib/focus.test.ts`, `web/src/lib/day.test.ts` e dois testes visuais em `web/e2e/hud.e2e.ts`.
