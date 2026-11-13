# Dia a dia

O que se usa todo dia sem pensar: tarefas e notas, o briefing, o foco, as cotações e o teste da internet. Tudo funciona por voz e pela área Dia a dia do HUD (tecla `2`). Um interruptor só liga e desliga o conjunto: `JARVIS_ENABLE_DAY` (vem ligado).

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

## Foco (FOC-47)

Blocos de trabalho com pausas, no estilo Pomodoro: "começa um foco de 25 minutos", "foco de 50 com pausa de 10, três blocos", "quanto falta do foco?", "pula esse bloco", "encerra o foco".

A contagem roda no HUD, não no agente. Por isso ela continua depois que o link fecha por silêncio, e fica salva no navegador: recarregar a página não zera o bloco. A cada troca tocam o som de timer e uma notificação ("Hora da pausa", "De volta ao foco", "Sessão concluída"). O bloco em andamento aparece na barra do topo, em qualquer área, e clicar nele abre o Dia a dia. Depois do último bloco de foco não há pausa: a sessão acaba.

Limites: foco de 1 a 180 minutos, pausa de 1 a 60 e de 1 a 12 blocos. Pela paleta (`Ctrl+K`), "Começar o foco" usa os tempos do painel.

Como a contagem é da aba do navegador, ela precisa de uma aba do HUD aberta para avisar. Com a aba fechada o horário não se perde: ao reabrir, o HUD passa pelos blocos que venceram e mostra onde a sessão está.

A rotina "modo foco" ([memoria-e-rotinas.md](memoria-e-rotinas.md)) continua existindo e faz outra coisa: minimiza as janelas, baixa o volume e põe um timer.

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
| `JARVIS_ENABLE_DAY` | `true` | Liga tarefas, notas, briefing, foco, cotações e teste de rede. `false` tira as ferramentas de voz e as rotas `/api/tasks` e `/api/network/test` |
| `JARVIS_BRIEFING_NEWS` | `principais notícias do Brasil hoje` | Assunto das manchetes do briefing. Vazio ou `false`: sem manchetes |

## Arquivos

- `tasks.py`, `quotes.py`, `netcheck.py` e `briefing.py` (que também tem a ferramenta do foco).
- `web/src/lib/day.ts` e `web/src/lib/focus.ts`; `web/src/components/DayView.tsx` e `web/src/components/cards/DayCards.tsx`.
- Testes: `tests/test_day.py`, `web/src/lib/focus.test.ts`, `web/src/lib/day.test.ts` e dois testes visuais em `web/e2e/hud.e2e.ts`.
