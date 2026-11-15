# Ferramentas sob demanda

Protocolo FER-33. Com tudo ligado o Jarvis tem 79 ferramentas, e com as integrações MCP passa de 100. O Gemini Live escolhe pior quando vê tantas de uma vez. Com as ferramentas sob demanda, ele começa só com as básicas e pede um grupo quando o assunto chega.

```env
JARVIS_TOOL_ROUTING=auto   # auto, true ou false
```

| Valor | O que faz |
| --- | --- |
| `auto` (padrão) | Separa em grupos quando a sessão tem mais de 60 ferramentas. Um servidor MCP conta as ferramentas do `permitir` dele |
| `true` | Separa sempre |
| `false` | Todas as ferramentas o tempo todo, como antes |

## Como funciona

1. O link abre com o núcleo e duas ferramentas: `use_tools` e `run_tool`. O prompt lista os grupos que existem nesta sessão. As integrações MCP começam a conectar em segundo plano.
2. Você pede "o que eu tenho hoje?". O modelo chama `use_tools(["agenda"])` e recebe as ferramentas do grupo, com a descrição e os parâmetros de cada uma.
3. Na mesma resposta, sem falar nada antes, ele chama `run_tool(name="get_agenda", arguments='{"day": "hoje"}')`, que roda a ferramenta de verdade. Só depois do resultado ele fala.
4. Na mesma conversa ele já conhece as ferramentas do grupo e pode chamar `run_tool` direto.

A placa do núcleo mostra "FER-33 · Buscando ferramentas" com o nome do grupo.

Nada reconecta: as ferramentas declaradas ao Gemini são as mesmas a conversa inteira. Uma ferramenta de grupo chamada com o argumento errado devolve o erro com os parâmetros certos, e o modelo tenta de novo.

## O núcleo

Fica sempre com o modelo: clima, pesquisa, notícias, hora, diagnóstico, timers, painéis do HUD, microfone, encerrar, voz, memória, tarefas e notas (`add_task`, `add_note`, `list_tasks`, `complete_task`, `remove_task`), rodar uma rotina (`run_routine`, para o "bom dia, Jarvis" não esperar), o `mcp_status` e todas as ferramentas de confirmar e cancelar por código. Ferramenta nova que ainda não está em grupo nenhum também fica no núcleo.

As tarefas e notas estão no núcleo de propósito: são pedidos de todo dia e, se ficassem num grupo, um "anota aí" cairia no `remember` (que é do núcleo) em vez de virar nota, porque o modelo usa a ferramenta que tem à mão. Elas custam cerca de 600 tokens a mais no núcleo.

## Os grupos

| Grupo | Ferramentas |
| --- | --- |
| `agenda` | `get_agenda`, `next_meeting`, `prepare_calendar_event`, `prepare_calendar_update`, `prepare_calendar_delete` |
| `email` | `check_email_address`, `draft_email` |
| `tela` | `look_at_screen`, `explain_screen`, `copy_fix`, `take_screenshot`, `watch_screen` |
| `janelas` | `open_app`, `close_app`, `open_website`, `save_shortcut`, `browser_tab`, `open_folder`, `manage_window`, `manage_screens`, `manage_layouts`, `arrange_windows`, `lock_computer` |
| `midia` | `play_youtube`, `open_streaming`, `media_control`, `set_volume` |
| `mouse` | `click_on_screen`, `move_mouse`, `type_text`, `press_keys`, `scroll`, `do_on_screen`, `start_dictation`, `write_here` |
| `gestos` | `gesture_control`, `gesture_shortcuts` |
| `camera` | `look_at_camera`, `camera_view`, `presence_control` |
| `rotinas` | `list_routines`, `save_routine`, `delete_routine`, `schedule_routine`, `set_routine_trigger` |
| `avisos` | `set_reminder`, `list_reminders`, `cancel_reminder`, `configure_alerts` |
| `diario` | `diary_lookup`, `forget_diary` |
| `apps` | `search_apps`, `prepare_app_install` |
| `dia` | `daily_briefing`, `focus_session`, `get_quotes`, `convert_value`, `network_speed` |
| `olho` | `osint_lookup` |
| um por servidor MCP | as ferramentas liberadas dele (`github`, `notion`...) |

Só entram os grupos das partes ligadas no `.env`. Os servidores MCP conectam em segundo plano quando o link abre; se o Jarvis pedir um deles antes de terminar, o `use_tools` espera a conexão. Servidor fora do ar devolve o motivo, para o Jarvis dizer isso em vez de inventar resultado.

## Medidas

Feitas no container com tudo ligado, contando o JSON das declarações que vão ao Gemini (cerca de 4 caracteres por token).

| Conjunto | Ferramentas | Tokens |
| --- | --- | --- |
| Todas | 79 | 14.200 |
| Núcleo | 32 (27 e 3.200 tokens antes das tarefas entrarem; elas somam cerca de 600) | 3.800 |
| Maior grupo (`janelas`) | 11 | 2.300 |
| Grupo médio | 2 a 5 | 300 a 1.100 |
| `.env` padrão (memória, diário e rotinas) | 25 | fica tudo junto no `auto` |

Por que não `Agent.update_tools`: era assim até outubro de 2026. No Gemini Live (livekit-agents 1.8.8) ele fecha o websocket e abre outro com o handle de retomada. Na prática isso deixava uns 7 segundos de silêncio depois do "Um instante.", o modelo emendava "não consigo acessar sua agenda" na mesma fala, e nos logs nenhuma ferramenta de grupo chegou a ser chamada depois da troca: a sessão retomada seguia com as ferramentas do começo. O Jarvis respondia "não encontrei nada", "a câmera está em uso" ou "não tenho acesso" sem ter tentado. Com `run_tool` o pedido roda na mesma resposta. No livekit-agents 1.8.11 o plugin passou a abrir uma sessão nova e reenviar a conversa em texto, mas trocar as ferramentas no meio de uma resposta ainda descarta a fila e a resposta em andamento, então o `run_tool` continua sendo o caminho.

Por que não pela transcrição: no Gemini Live a transcrição final da sua fala só chega quando a resposta dele termina, tarde demais para escolher as ferramentas daquele pedido. A escolha fica com o modelo, pelo `use_tools`.

Por que `auto` e não `true`: cada assunto novo custa uma chamada a mais (`use_tools`) e a lista do grupo no contexto. Com o `.env` padrão são 25 ferramentas e o ganho não paga isso. Com tudo ligado, o modelo deixa de ver 11.000 tokens de ferramentas que não têm nada a ver com o pedido.

## Confirmações

As ferramentas de confirmar e cancelar nunca estão em grupo. Um email, uma instalação, um clique ou um evento da agenda esperando o código continuam confirmáveis direto pela ferramenta de confirmar, sem `use_tools`. A frase e o código são os mesmos de sempre ([seguranca.md](seguranca.md#confirmação-por-voz)).

## Troca de modelo

Se o Gemini cair e a conversa passar para um modelo de reserva ([modelos.md](modelos.md)), `use_tools` e `run_tool` vão junto, com o resto do núcleo.
