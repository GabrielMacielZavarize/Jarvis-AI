# Ferramentas sob demanda

Protocolo FER-33. Com tudo ligado o Jarvis tem 75 ferramentas, e com as integrações MCP passa de 100. O Gemini Live escolhe pior quando vê tantas de uma vez. Com as ferramentas sob demanda, ele começa só com as básicas e pede um grupo quando o assunto chega.

```env
JARVIS_TOOL_ROUTING=auto   # auto, true ou false
```

| Valor | O que faz |
| --- | --- |
| `auto` (padrão) | Separa em grupos quando a sessão tem mais de 60 ferramentas. Um servidor MCP conta as ferramentas do `permitir` dele |
| `true` | Separa sempre |
| `false` | Todas as ferramentas o tempo todo, como antes |

## Como funciona

1. O link abre com o núcleo e a ferramenta `use_tools`. O prompt lista os grupos que existem nesta sessão.
2. Você pede "o que eu tenho hoje?". O modelo não tem a agenda, então chama `use_tools(["agenda"])` e diz só "Um instante.".
3. Quando essa frase termina, o agente entrega as ferramentas do grupo ao modelo (`Agent.update_tools`) e pede que ele continue o seu pedido. Você não precisa repetir nada.
4. O grupo fica até o fim da conversa. Passando de 4 grupos, o usado há mais tempo sai na próxima troca.

A placa do núcleo mostra "FER-33 · Carregando ferramentas" com o nome do grupo.

## O núcleo

Fica sempre com o modelo: clima, pesquisa, notícias, hora, diagnóstico, timers, painéis do HUD, microfone, encerrar, voz, memória, rodar uma rotina (`run_routine`, para o "bom dia, Jarvis" não esperar), o `mcp_status` e todas as ferramentas de confirmar e cancelar por código. Ferramenta nova que ainda não está em grupo nenhum também fica no núcleo.

## Os grupos

| Grupo | Ferramentas |
| --- | --- |
| `agenda` | `get_agenda`, `next_meeting`, `prepare_calendar_event`, `prepare_calendar_update`, `prepare_calendar_delete` |
| `email` | `check_email_address`, `draft_email` |
| `tela` | `look_at_screen`, `explain_screen`, `copy_fix`, `take_screenshot` |
| `janelas` | `open_app`, `close_app`, `open_website`, `save_shortcut`, `browser_tab`, `open_folder`, `manage_window`, `manage_screens`, `manage_layouts`, `arrange_windows`, `lock_computer` |
| `midia` | `play_youtube`, `open_streaming`, `media_control`, `set_volume` |
| `mouse` | `click_on_screen`, `move_mouse`, `type_text`, `press_keys`, `scroll`, `do_on_screen`, `start_dictation`, `write_here` |
| `gestos` | `gesture_control`, `gesture_shortcuts` |
| `camera` | `look_at_camera`, `camera_view`, `presence_control` |
| `rotinas` | `list_routines`, `save_routine`, `delete_routine`, `schedule_routine` |
| `avisos` | `set_reminder`, `list_reminders`, `cancel_reminder`, `configure_alerts` |
| `apps` | `search_apps`, `prepare_app_install` |
| um por servidor MCP | as ferramentas liberadas dele (`github`, `notion`...) |

Só entram os grupos das partes ligadas no `.env`. O servidor MCP conecta quando o grupo dele entra pela primeira vez, e não quando o link abre. Até lá o `mcp_status` diz "ainda conectando".

## Medidas

Feitas no container com tudo ligado, contando o JSON das declarações que vão ao Gemini (cerca de 4 caracteres por token).

| Conjunto | Ferramentas | Tokens |
| --- | --- | --- |
| Todas | 75 | 13.000 |
| Núcleo | 28 | 3.400 |
| Maior grupo (`janelas`) | 11 | 2.300 |
| Grupo médio | 2 a 5 | 300 a 900 |
| `.env` padrão (memória e rotinas) | 22 | fica tudo junto no `auto` |

O que o `update_tools` faz no Gemini Live, conferido no livekit-agents 1.8.8 com um cliente falso (`tests/test_tool_routing.py`):

| Pergunta | Resposta |
| --- | --- |
| Reabre a sessão? | Sim. O plugin não troca ferramentas numa sessão aberta (`mutable_tools=False`): fecha o websocket e abre outro com as ferramentas novas |
| Perde contexto? | Não. A sessão nova volta pelo handle de retomada e o plugin reenvia só o que veio depois dele |
| Quanto atrasa? | No agente, uns milissegundos. O resto é abrir a conexão com o Google, que não deu para medir aqui (sem chave) |
| O que dá errado no meio de uma resposta? | A fila de mensagens é descartada e a resposta em andamento se perde, inclusive a da própria ferramenta. Por isso a troca espera o "Um instante." terminar |

Por que não pela transcrição: no Gemini Live a transcrição final da sua fala só chega quando a resposta dele termina. Trocar as ferramentas ali serviria só para o pedido seguinte, e trocar durante a sua fala perderia o áudio já enviado. A escolha fica com o modelo, pelo `use_tools`, que custa uma chamada curta e a frase "Um instante." antes da reconexão.

Por que `auto` e não `true`: cada grupo novo custa essa frase e uma reconexão, perto de 1 a 2 segundos na primeira vez do assunto. Com o `.env` padrão são 22 ferramentas e o ganho não paga a espera. Com tudo ligado, o modelo deixa de ver 9.600 tokens de ferramentas que não têm nada a ver com o pedido.

## Confirmações

As ferramentas de confirmar e cancelar nunca estão em grupo. Um email, uma instalação, um clique ou um evento da agenda esperando o código continuam confirmáveis mesmo que o grupo que preparou a ação tenha saído. A frase e o código são os mesmos de sempre ([seguranca.md](seguranca.md#confirmação-por-voz)).

## Troca de modelo

Se o Gemini cair e a conversa passar para um modelo de reserva ([modelos.md](modelos.md)), os grupos carregados vão junto.
