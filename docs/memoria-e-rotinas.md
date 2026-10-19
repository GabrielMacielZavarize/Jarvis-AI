# Memória e rotinas

## Memória entre conversas

Protocolo MEM-23. Vem ligada (`JARVIS_ENABLE_MEMORY=false` desliga).

Peça "lembra que eu prefiro lo-fi pra programar", "anota que minha reunião de segunda é às 9" ou "não esquece que eu moro em Criciúma". Cada fato vai para o `memoria.json` (na pasta do projeto, fora do git) com categoria (perfil, preferência, pessoas, trabalho, agenda ou outros) e data. No começo de cada conversa um resumo curto entra nas instruções do Jarvis, então ele já sabe seu nome, sua cidade e suas preferências.

"O que você sabe sobre mim?" ou "qual é a minha reunião?" chamam o `recall`, e a lista aparece no painel Memória.

"Esquece isso" (logo depois de guardar) ou "apaga o que eu falei do lo-fi" chamam o `forget`. Se várias memórias combinarem, o Jarvis pergunta qual. "Esquece tudo que você sabe sobre mim" apaga tudo.

"A reunião agora é às 10" guarda a nova e remove a antiga (`replaces`).

No painel Memória, a lixeira de cada item vira "Apagar?" e o segundo clique apaga, pelo agente, via RPC `jarvis.memory`.

Dá para editar o arquivo à mão:

```json
{"memories": [{"fact": "...", "category": "perfil"}]}
```

Se o arquivo ficar ilegível, ele é guardado como `memoria.corrompido-<data>.json` antes de qualquer gravação.

As regras do que pode e do que não pode ser guardado estão em [seguranca.md](seguranca.md#memória).

## Rotinas

Protocolo ROT-24. Também vem ligado (`JARVIS_ENABLE_ROUTINES=false` desliga). Os passos que mexem no PC precisam de `JARVIS_ENABLE_PC_CONTROL=true`.

Uma rotina é uma lista de passos que o Jarvis roda em sequência com as ferramentas que ele já tem. Para rodar, diga o nome dela.

| Rotina | O que faz |
| --- | --- |
| Bom dia ("Bom dia, Jarvis") | Cumprimenta pelo horário, diz o clima de `JARVIS_HOME_CITY`, as manchetes do dia e os lembretes de agenda da memória, aplica o layout de janelas "trabalho" e toca uma playlist lo-fi no YouTube |
| Modo foco | Minimiza as janelas, põe o volume em 15%, liga um timer Pomodoro de 25 minutos e deixa uma nota no HUD |
| Modo jogo | Abre a Steam e o Discord e põe o volume em 60% |
| Boa noite | Cumprimenta, salva as janelas como layout "noite", pausa a mídia e pergunta antes de bloquear o PC |

Cada passo aparece no painel Rotina do HUD como feito, falhou ou esperando o seu sim. Um passo que falha (layout que não existe, app que não abre, rede fora) não derruba os outros, e o Jarvis diz o que falhou e por quê. Um passo travado desiste depois de 60 segundos.

O layout "trabalho" do bom dia é o que você salvou com "salva esse layout como trabalho". Sem ele, esse passo falha e o resto segue.

### Criando e agendando

Por voz: "cria uma rotina estudo que abre o Notion e põe lo-fi", "coloca o Spotify no modo jogo", "muda o modo foco para 50 minutos", "apaga a rotina estudo", "quais rotinas eu tenho?".

Para agendar: "todo dia útil às 8h roda o bom dia", "toda sexta às 19h roda o modo jogo", "para de rodar o bom dia sozinho". Na hora marcada, com o `python jarvis.py` aberto, o HUD conecta o link pela mesma via da palavra de ativação (abrindo o navegador se não houver aba), roda a rotina e o Jarvis fala o resultado. Se a conversa já estiver aberta, a rotina roda ali mesmo. Se o PC ligar até 10 minutos depois do horário, a rotina daquele dia ainda roda.

### O arquivo

As rotinas ficam no `rotinas.json` (fora do git). Sem o arquivo valem as quatro de fábrica, e a primeira edição grava todas nele. Dá para editar à mão, e cada passo é uma linha `ação: argumento`:

```json
{
  "version": 1,
  "routines": {
    "estudo": {
      "name": "Estudo",
      "aliases": ["hora de estudar"],
      "steps": ["app: Notion", "youtube: lo-fi para estudar", "timer: 50 Estudo", "volume: 25"],
      "schedule": {"days": [0, 1, 2, 3, 4], "time": "19:00", "enabled": true}
    }
  }
}
```

Ações aceitas:

| Ação | Argumento |
| --- | --- |
| `greet`, `reminders`, `time`, `minimize`, `lock` | Nenhum |
| `weather` | Opcional: a cidade |
| `news` | O tema |
| `timer` | Minutos e rótulo |
| `note` | `título \| texto` |
| `layout`, `save_layout` | Nome do layout |
| `youtube`, `spotify` | A busca |
| `stream` | `serviço \| busca` |
| `site` | O endereço |
| `app`, `close` | Nome do app |
| `folder` | A pasta |
| `volume` | De 0 a 100, `mute` ou `unmute` |
| `media` | `stop`, `play_pause`, `next` ou `previous` |

Os dias vão de 0 (segunda) a 6 (domingo).

O que pode e o que não pode entrar numa rotina está em [seguranca.md](seguranca.md#rotinas).

### Como testar

No Windows, com `JARVIS_ENABLE_PC_CONTROL=true` e `JARVIS_HOME_CITY` no `.env` (`python jarvis.py --rebuild` na primeira vez):

1. Arrume as janelas de trabalho nos 3 monitores e diga "salva esse layout como trabalho". Minimize tudo.
2. "Bom dia, Jarvis": o painel Rotina mostra os 6 passos um a um. O Jarvis fala o clima, 2 ou 3 manchetes e os lembretes, as janelas voltam ao lugar e a playlist abre.
3. "Apaga o layout trabalho" e repita o bom dia: o passo do layout falha, o resto roda e o Jarvis diz que o layout não existe.
4. "Modo foco": janelas minimizadas, volume em 15% e o timer de 25 minutos no HUD.
5. "Boa noite": layout "noite" salvo, mídia pausada e a pergunta do bloqueio. Responda "não" (nada acontece), depois rode de novo e responda "sim, pode" (a tela bloqueia).
6. "Cria uma rotina estudo que abre o Notion e põe lo-fi" e depois "roda a rotina estudo".
7. "Todo dia às (daqui a 2 minutos) roda o modo foco", feche a aba do HUD e espere: o navegador abre sozinho, o link conecta e o Jarvis fala o resultado. Repita com uma conversa aberta: a rotina roda nela em até 15 segundos. No fim, "para de rodar o modo foco sozinho".
