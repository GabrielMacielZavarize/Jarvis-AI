# Painel de saúde

O painel Saúde (SAU-40) guarda um histórico do próprio Jarvis para calibrar o `.env` com números. Fica na coluna da direita do HUD e pode ser arrastado como os outros.

Vem ligado. `JARVIS_HEALTH=false` no `.env` para de gravar e o painel mostra "desligado".

## O que é medido

| Medida | De onde vem | Para que serve |
| --- | --- | --- |
| Tempo de resposta | Agente, do fim da sua fala até a primeira palavra do Jarvis | Ver se piorou de um dia para o outro |
| Ferramenta com erro | Agente, quando uma ferramenta termina em erro | Achar a que falha sempre e a última mensagem |
| Pausa de modelo | Agente, quando o Gemini cai por cota, sobrecarga ou indisponibilidade | Decidir se vale um modelo reserva ou o rodízio |
| Troca de modelo | Agente, quando a conversa passa para um reserva | Contar quantas vezes isso aconteceu |
| Ativação | Servidor, a cada "Jarvis" ou "Friday" aceito | Base das outras contas da palavra |
| Ativação sem fala | HUD, quando o link aberto pela palavra fecha por silêncio sem você ter falado | Achar falsos positivos |
| Quase ativação | Detector, quando a pontuação chega a 60% do limiar sem passar | Ver se o limiar está alto demais para a sua voz |
| Busca na memória | Agente, a cada `recall` com a busca pelo sentido | Ver quantas buscas não acharam nada e a nota média |

Nenhum evento leva texto da conversa. Só nomes (ferramenta, modelo, palavra), números e a mensagem curta de erro da ferramenta.

## O painel

Fechado, ele mostra quantas sugestões há e a primeira delas. Em Detalhes aparecem:

- o gráfico da mediana diária do tempo de resposta, com a mediana das últimas 24 h e a do dia anterior;
- uma linha por palavra de ativação: limiar, ativações, ativações sem fala e quase ativações com o pico;
- as ferramentas com erro, as pausas de cada modelo e o número de trocas;
- as buscas na memória pelo sentido.

Os botões 24 h, 7 dias e 30 dias trocam a janela. Limpar apaga o histórico e só aparece no próprio PC.

## Sugestões

| Situação | Sugestão |
| --- | --- |
| A palavra ativou 3 vezes ou mais sem você falar | Subir `JARVIS_WAKE_THRESHOLD_<PALAVRA>` em 0.10 |
| Pelo menos 5 quase ativações e o dobro das ativações | Descer o mesmo limiar em 0.05, se era você chamando |
| Mediana das últimas 24 h pelo menos 25% e 0,3 s pior que a do dia anterior, com 5 respostas ou mais em cada | Aviso de que o tempo de resposta piorou |
| Ferramenta com 3 erros ou mais | O nome e o último erro |
| Modelo pausado por cota 3 vezes ou mais | `GOOGLE_FALLBACK_MODELS` ou `JARVIS_MODEL_ROTATION=rotate` |
| 5 buscas ou mais na memória e 40% delas sem resultado | Descer `JARVIS_MEMORY_MIN_SIMILARITY`, se o fato existia |

As sugestões só apontam o ajuste. Nada muda no `.env` sozinho.

## Onde fica

O servidor grava tudo em `saude.db` (SQLite) na pasta do projeto, fora do git. Eventos com mais de 30 dias saem sozinhos, e o arquivo guarda no máximo 50 mil. Com o servidor fora do ar, o evento se perde e o Jarvis segue normal.

| Rota | Quem usa |
| --- | --- |
| `GET /api/health?days=7` | O painel. O celular pareado também lê |
| `POST /api/health/event` | Agente, detector e HUD do PC. O celular não grava |
| `DELETE /api/health` | O botão Limpar, só no PC |
