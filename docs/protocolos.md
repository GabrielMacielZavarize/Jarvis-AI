# Protocolos

Cada ferramenta do Jarvis tem um código de protocolo, que aparece no HUD (na placa sobre o núcleo e no painel Protocolos) e nas linhas do terminal. Você não precisa saber os nomes das ferramentas: é só pedir do jeito que está nos exemplos.

| Código | Ferramentas | O que faz | Exemplos |
| --- | --- | --- | --- |
| WX-01 | `get_weather` | Clima atual e previsão de 5 dias | "Como está o tempo em Lisboa?" |
| NET-02 | `search_web` | Pesquisa no DuckDuckGo | "Pesquise sobre fusão nuclear." |
| NWS-03 | `search_news` | Manchetes recentes | "Últimas notícias de tecnologia." |
| CHR-04 | `get_current_time` | Hora local ou de qualquer cidade | "Que horas são em Tóquio?" |
| SYS-05 | `run_diagnostics` | CPU, RAM, disco, bateria e uptime | "Rode um diagnóstico do sistema." |
| TMR-06 | `set_timer`, `get_timers` | Contagem regressiva com aviso falado e quanto falta em cada timer da conversa | "Timer de 10 minutos pro café.", "Quanto tempo falta pro timer acabar?" |
| HUD-07 | `show_on_hud` | Painel livre com listas, passos e resumos | "Mostre os passos no painel." |
| HUD-07 | `set_hud_appearance` | Persona do HUD (J.A.R.V.I.S., Mark III, F.R.I.D.A.Y. ou Stealth; o jeito de falar e a voz trocam logo depois da confirmação) e modo cinema. Sem HUD conectado, avisa que nada mudou | "Chama a Friday.", "Modo Mark III.", "Modo discreto.", "Deixa o HUD roxo.", "Modo cinema.", "Mostra os painéis de novo." |
| HUD-07 | `manage_hud_panels` | Lista, fecha e amplia painéis pelo tipo, pelo título ou "o último". Avisa quando nada foi fechado | "Feche a aba.", "Fecha a aba de reprodução.", "Maximiza o rascunho da lista de compras.", "Fecha essas abinhas da esquerda." |
| MED-08 | `play_youtube`, `open_streaming`, `media_control` | YouTube, lives, Spotify, Twitch e controle de mídia | "Toque lo-fi no YouTube.", "Abre a live do Gaules.", "Toca Guns N' Roses no Spotify.", "Pausa." |
| PC-09 | `open_app`, `close_app`, `open_folder`, `lock_computer`, `take_screenshot` | Apps, pastas, bloqueio de tela e print | "Abra o Spotify.", "Bloqueie a tela." |
| WEB-10 | `open_website`, `browser_tab`, `save_shortcut` | Sites e abas do navegador. Com um monitor no pedido, abre numa janela própria naquela tela | "Abre o Google Maps.", "Abre o YouTube no monitor 1.", "Feche a aba do YouTube.", "Salva esse site como portal SATC." |
| AUD-11 | `set_volume` | Volume do sistema | "Volume em 30%." |
| COM-12 | `check_email_address`, `draft_email`, `confirm_email_send`, `cancel_pending_email` | Email com rascunho e código de confirmação | "Escreva um email para gabriel arroba gmail ponto com..." |
| JAN-13 | `manage_window`, `manage_screens` | Move janelas entre monitores pelo número do "Identificar" ou pelo nome da tela, volta à posição anterior, maximiza, minimiza, encaixa e fecha. Lista, apelida e corrige a numeração das telas | "Joga o Chrome na tela 1.", "Manda o Chrome pro monitor de cima.", "Volta pra onde estava.", "Salva a tela vertical como tela de código.", "A tela 1 é o notebook." |
| VIS-14 | `look_at_screen` | Print de um monitor ou janela, mostrado no HUD e analisado | "O que tem aberto no PhpStorm?" |
| APP-15 | `search_apps`, `prepare_app_install`, `confirm_app_install`, `cancel_app_install` | Instala apps pelo winget com código de confirmação | "Instala o VLC pra mim." |
| MIC-16 | `check_microphone` | Qual microfone está escolhido no painel Sistema, se está mudo e quando chegou som. Dos padrões do Windows, só os nomes | "Qual microfone está conectado contigo?" |
| PWR-17 | `end_session` | Despede-se e encerra o link, como o botão Encerrar link. Não desliga o PC | "Tchau, Jarvis.", "Jarvis, desligar." |
| GST-18 | `gesture_control`, `gesture_shortcuts` | Liga e desliga os gestos, o mouse no ar e o painel de gestos. Lista, explica e muda os gestos personalizáveis. O painel Gestos do HUD faz o mesmo por botões | "Liga os gestos.", "Liga o mouse no ar.", "Mostra o painel de gestos.", "Os gestos estão ligados?", "Lista meus gestos.", "O que faz o rock?", "Quando eu fizer joinha, pausa a música." |
| CAM-19 | `look_at_camera`, `camera_view` | Foto da webcam, analisada e mostrada no painel Câmera. Mostra ou esconde o feed ao vivo e desliga a câmera | "O que você está vendo?", "Que livro é esse aqui?", "Mostra a câmera.", "Desliga a câmera." |
| MOU-20 | `click_on_screen`, `move_mouse`, `type_text`, `press_keys`, `scroll`, `do_on_screen`, `confirm_screen_action`, `cancel_screen_action` | Mouse e teclado de verdade: acha o elemento num print, leva o cursor até ele e clica. Digita, usa atalhos liberados, rola e faz tarefas curtas de até 8 passos. Clique que envia, compra, paga, publica, apaga ou confirma pede código | "Clica no botão de play.", "Digita olá no bloco de notas.", "Rola a página.", "Abre o menu de configurações do Discord." |
| LAY-21 | `manage_layouts`, `arrange_windows` | Salva e aplica layouts de janelas, junta tudo numa tela, leva as janelas de uma tela para outra, mostra a área de trabalho e desfaz tudo de uma vez | "Salva esse layout como modo trabalho.", "Modo trabalho.", "Organiza tudo pro notebook.", "Manda tudo do notebook pro monitor de cima.", "Mostra a área de trabalho.", "Desfaz." |
| MEM-23 | `remember`, `recall`, `forget` | Memória entre conversas, com busca pelo sentido e painel para listar e apagar | "Lembra que minha reunião de segunda é às 9.", "O que você sabe sobre mim?", "Esquece isso." |
| ROT-24 | `run_routine`, `list_routines`, `save_routine`, `delete_routine`, `schedule_routine`, `confirm_routine_step` | Várias ferramentas em sequência, com os passos no painel Rotina e agendamento por horário | "Bom dia, Jarvis.", "Modo foco.", "Cria uma rotina estudo que abre o Notion e põe lo-fi.", "Todo dia útil às 8h roda o bom dia." |
| PRS-25 | `presence_control` | Liga e desliga a presença pela webcam e escolhe se o PC bloqueia quando você sai | "Liga a presença.", "Não bloqueia quando eu sair.", "Pode bloquear quando eu sair." |
| AGD-27 | `get_agenda`, `next_meeting`, `prepare_calendar_event`, `prepare_calendar_update`, `prepare_calendar_delete`, `confirm_calendar_change`, `cancel_calendar_change` | Lê o Google Agenda e cria, altera e apaga eventos com código de confirmação. Painel Agenda e aviso antes das reuniões | "O que eu tenho hoje?", "E amanhã?", "Qual minha próxima reunião?", "Marca dentista sexta às 15h.", "Desmarca a reunião das 10." |
| PRO-28 | `set_reminder`, `list_reminders`, `cancel_reminder`, `configure_alerts` | Lembretes com hora e avisos sozinhos de bateria, CPU e RAM, downloads e disco | "Me lembra amanhã às 10h de ligar pro contador.", "Quais lembretes eu tenho?", "Para de me avisar sobre bateria." |
| DIT-29 | `start_dictation`, `write_here` | Modo ditado: o que você fala vira texto no campo em foco até "fim do ditado". Ou uma frase só | "Jarvis, modo ditado.", "Escreve aqui: chego em 10 minutos." |
| VOZ-30 | `change_voice` | Troca a voz, lista as vozes no HUD e volta à padrão | "Troca sua voz para Orus.", "Quais vozes você tem?", "Volta pra sua voz normal." |
| TEL-31 | `explain_screen`, `copy_fix` | Lê a seleção, a janela em foco, o trecho perto do cursor ou o lugar apontado com o dedo e explica no painel. Copia o código sugerido para a área de transferência | "Explica esse erro.", "O que tem de errado aqui?", "O que esse código faz?", "Resume essa página.", "Traduz isso pro inglês.", "Copia a correção." |

| MCP-32 | `mcp_status`, `confirm_mcp_action`, `cancel_mcp_action` e as ferramentas liberadas no `mcp.json` (`github_list_issues`...) | Usa ferramentas de servidores MCP (GitHub, Notion, Spotify...). Só as do `permitir` chegam ao modelo, e as que escrevem pedem código | "Quais issues abertas eu tenho no Jarvis-AI?", "Procura a página da reunião no Notion.", "Quais integrações você tem?" |

A palavra de ativação (WAK-22) e o celular na rede de casa (LAN-26) não têm ferramenta de voz. Estão em [voz.md](voz.md#palavra-de-ativação) e [celular.md](celular.md).

## O que liga cada protocolo

| Protocolos | Como ligar |
| --- | --- |
| MED, PC, WEB, AUD, JAN, VIS, LAY e TEL | `JARVIS_ENABLE_PC_CONTROL=true` |
| COM | `JARVIS_ENABLE_EMAIL_TOOL=true` (veja [seguranca.md](seguranca.md#email)) |
| APP | `JARVIS_ENABLE_APP_INSTALL=true` |
| CAM | `JARVIS_ENABLE_CAMERA=true` |
| GST | `JARVIS_ENABLE_GESTURES=true` ou `python jarvis.py --gestures` |
| MOU e DIT | `JARVIS_ENABLE_COMPUTER_USE=true` |
| PRS | `JARVIS_PRESENCE=true`, junto com `JARVIS_ENABLE_CAMERA=true` |
| AGD | `JARVIS_ENABLE_CALENDAR=true`, depois do login no Google ([agenda.md](agenda.md)) |
| PRO | `JARVIS_PROACTIVE=true` |
| MEM | Vem ligado. `JARVIS_ENABLE_MEMORY=false` desliga |
| ROT | Vem ligado. `JARVIS_ENABLE_ROUTINES=false` desliga. Os passos que mexem no PC precisam de `JARVIS_ENABLE_PC_CONTROL=true` |
| WAK-22 | `JARVIS_WAKE_WORD=true` |
| LAN-26 | `python jarvis.py --lan` ou `JARVIS_LAN=true` |
| MCP | `JARVIS_ENABLE_MCP=true` e os servidores no `mcp.json` (veja [integracoes.md](integracoes.md)) |

## Painéis, abas e atalhos de site

Quando você fala em "aba" ou "abinha" na tela ou na esquerda, o Jarvis entende que são os painéis do HUD. Ele só mexe nas abas do navegador quando você cita o site ("feche a aba do YouTube"). Rascunhos de email esperando confirmação e timers em andamento não somem da coluna quando chegam painéis novos.

Serviços conhecidos (Google Maps, Gmail, Drive, Claude, ChatGPT, GitHub e outros) abrem pelo nome. Para os seus sites, peça "salva esse site como ..." ou edite o `atalhos.json`:

```json
{"portal SATC": "https://..."}
```

Esse arquivo fica fora do git.

Depois de atualizar o código, recompile o HUD com `python jarvis.py --rebuild`. Sem isso o navegador continua com a versão antiga e não entende os títulos, o microfone nem o "desligar".
