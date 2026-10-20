# Diário das conversas

Protocolo DIA-36. Vem ligado (`JARVIS_DIARY=false` desliga).

Quando o link fecha, o Jarvis escreve um resumo curto da conversa: o que você pediu, o que foi feito ou decidido e o que ficou pendente. Depois dá para perguntar:

| Pergunta | O que ele procura |
| --- | --- |
| "O que eu te pedi ontem?" | As conversas de ontem |
| "O que a gente fez na sexta?" | As conversas da última sexta antes de hoje |
| "Onde paramos no projeto do Jarvis?" | As conversas sobre o assunto, pelo sentido |
| "O que ficou pendente essa semana?" | As conversas de segunda até hoje |

A resposta vem falada e o painel Diário do HUD mostra as conversas agrupadas por dia, com o pedido, o feito e o pendente de cada uma.

Datas que ele entende: "hoje", "ontem", "anteontem", o dia da semana, "18/10", "dia 5", "há 3 dias", "semana passada" e "essa semana". "Na sexta" é sempre a última sexta antes de hoje. Para a de hoje, diga "hoje".

## Como o resumo é feito

No fim da conversa, a transcrição (só as suas falas e as do Jarvis, sem o resultado das ferramentas) vai para o Gemini pela API normal, com a mesma `GOOGLE_API_KEY` e o modelo de `JARVIS_COMPUTER_USE_MODEL`. Ele devolve um título, até cinco itens de pedido, de feito e de pendente e algumas palavras-chave. Isso vai para o `diario.json`, na pasta do projeto e fora do git, com a data e a hora.

Conversa curta não vira entrada: menos de duas falas suas ou menos de 8 palavras no total ("que horas são?", "obrigado"). Se o modelo achar que não houve nada para lembrar (só cumprimento, a hora, uma curiosidade), também não.

O resumo tem até 8 segundos. O LiveKit fecha o processo da conversa pouco depois do fim, e o que passar disso fica sem entrada. Sem a chave do Google (backend da OpenAI, por exemplo), nada é resumido.

## Busca pelo sentido

A busca pelo assunto usa os mesmos embeddings da [memória](memoria-e-rotinas.md#busca-pelo-sentido): cada entrada vira um vetor, guardado dentro do próprio `diario.json`. "Onde paramos no projeto do Jarvis?" acha "Bug do login no Jarvis-AI" mesmo sem a palavra "projeto". Os ajustes são os da memória (`JARVIS_MEMORY_EMBEDDINGS`, `JARVIS_MEMORY_MIN_SIMILARITY` e `JARVIS_MEMORY_TOP_K`), e valem mesmo com a memória desligada. Sem rede, sem chave ou com os embeddings desligados, a busca é por palavras.

## Apagar

| Pedido | O que acontece |
| --- | --- |
| "Esquece essa conversa" | A conversa atual não é resumida no fim. As anteriores ficam |
| "Apaga o diário de ontem" | Apaga todas as conversas de ontem |
| "Apaga a conversa do lo-fi" | Apaga essa. Se várias combinarem, o Jarvis pergunta qual |
| "Apaga o diário inteiro" | Apaga tudo. Precisa de "tudo" ou "inteiro" na fala |

Como no `forget` da memória, só vale com "esquece" ou "apaga" na sua última fala. No painel Diário, o × de cada conversa vira "Apagar?" e o segundo clique apaga, pelo agente, via RPC `jarvis.diary`.

## Desligar

```env
JARVIS_DIARY=false
```

Desligado, nenhuma conversa é resumida nem enviada para isso, e as ferramentas `diary_lookup` e `forget_diary` somem. O `diario.json` que já existir continua na pasta; apague o arquivo para limpar tudo.

O que vai para o Google e o que é filtrado antes está em [seguranca.md](seguranca.md#diário-das-conversas).
