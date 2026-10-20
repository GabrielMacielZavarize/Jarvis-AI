# Testes automáticos

```bash
python -m unittest discover -s tests -v
cd web && npm test && npm run build
```

O `pytest` também roda a pasta `tests` (`python -m pytest -q tests`). Alguns testes dependem do ambiente: os de memória esperam o fuso `America/Sao_Paulo` (`TZ=America/Sao_Paulo` fora do Brasil) e os de controle do PC precisam de uma tela, porque o pyautogui não importa sem `DISPLAY` no Linux.

Tudo roda com mocks: os testes não instalam, não tocam, não abrem, não clicam e não movem nada no seu computador, nem abrem a webcam ou o microfone. O que só dá para conferir na máquina real está no [roteiro de testes](ROTEIRO_DE_TESTES.md).

## O que está coberto

| Área | O que os testes conferem |
| --- | --- |
| Núcleo | Settings, seleção de backend, registro de ferramentas, clima e previsão, pesquisa, notícias, horário, diagnóstico, timers, painéis do HUD e publicação no data channel |
| Modelos | Fila de modelos do Gemini, pausa por cota (a diária vai até a meia-noite da Califórnia) e por sobrecarga, rodízio e troca de modelo no meio da conversa com uma sessão falsa |
| Email | Endereço ditado e confirmação por voz |
| Instalação | Busca e instalação via winget |
| Janelas e telas | Numeração das Configurações, nomes, apelidos, layouts e desfazer em lote |
| Mídia | Lives do YouTube com HTML de exemplo, Twitch, Spotify e fechamento da aba certa |
| Câmera | Hub com webcam falsa e vários consumidores, contagem de referência, endpoints e as ferramentas de visão |
| Gestos | Mãos sintéticas (poses, suavização, histerese, quadros ruins), calibração, replay de traces, máquina de estados, monitor vizinho com a geometria real dos 3 monitores, os gestos personalizáveis com o `gestos.json` e as ações com mocks. No apontar: o ponto sem mexer no cursor, o ponto que não escorrega ao baixar a mão, o tempo máximo, a fala que impede o mouse no ar (também no meio da contagem), o pixel e a mira no motor e a sessão de voz avisando quando você fala |
| Mouse e teclado | Conversão de coordenadas com os três monitores reais, DPI, allowlist de atalhos, recusa de senhas e janelas do sistema, confirmação de cliques e parse da resposta do modelo de visão |
| Memória | Pedido na última fala, recusa de senhas, documentos e cartões, resumo na sessão seguinte e o painel. Na busca pelo sentido, com um embedder falso de vetores fixos: perguntas sem as palavras do fato, pergunta sem relação, palavra exata primeiro, vetores das memórias antigas numa chamada só, vetor da memória nova em segundo plano, `forget` e painel apagando o vetor, senha que nunca vira vetor, queda para as palavras sem rede ou com a API lenta e o `--reindex` |
| Palavra de ativação | Microfone pelo nome que o navegador mostra, detector, pausa durante o link, aviso ao HUD e encerramento por silêncio. Com duas palavras: limiar de cada uma, a maior pontuação vencendo, o modelo da Friday que falta (só "Jarvis"), o nome no aviso ao servidor, a persona gravada antes de o HUD saber, "Jarvis" que não tira do Mark III e nada mudando com uma palavra só |
| Rotinas | Passos, falhas parciais, timeout, confirmação do bloqueio, edição por voz e agendamento com relógio falso |
| Assistente de tela | Ordem de leitura (seleção, área de transferência, texto da janela ou do cursor, print só sem texto), HUD em foco, recusa de cofres de senha, ocultação de segredos, região do cursor nos monitores de x negativo, o ponto apontado com o dedo no lugar do cursor (a janela embaixo dele, sem a seleção da janela em foco, e as mesmas recusas), prompt e parse do modelo, queda para a sessão de voz e cópia sem digitar. Tudo com UI Automation, prints, área de transferência e modelo falsos |
| Modo ditado | Normalização (comandos falados viram texto e teclas, pontuação automática, maiúsculas, "ponto" e "vírgula" como palavras) e a máquina de estados (parciais e final do Gemini, a fala que ligou o modo nunca é digitada, silêncio do Jarvis, fim do ditado, desfazer, Shift+Enter em apps de conversa, recusas, Esc, mouse, silêncio e troca de campo), com teclado falso |
| Voz | `tests/test_voices.py` confere `JARVIS_VOICE`, a lista de vozes contra a do plugin, o `voz.json` (uma voz por persona, e o arquivo antigo valendo para o J.A.R.V.I.S.), a ferramenta `change_voice` (troca na hora depois da resposta) e o tom do prompt |
| Personas | `tests/test_personas.py` confere o `persona.json`, o prompt do J.A.R.V.I.S. intacto, a persona e a saudação de cada uma, a troca que mantém memórias e contexto, a espera pela conversa quieta, a troca ao vivo (instruções, voz e apresentação) e o `/api/persona` |
| Gestos no HUD | `tests/test_gesture_management.py` confere o catálogo, os gestos que fazem a mesma coisa, a API `/api/gestures` com as recusas da voz e outros sites barrados, e os botões pelo RPC do agente |
| Build do HUD | `tests/test_web_build.py` confere que o `--rebuild` roda o `npm install` quando o `package-lock.json` mudou |
| Agenda | Datas em português com relógio fixo, busca do evento falado ("a reunião das 10"), criar, alterar e apagar só com "confirmar agenda" e o código, erros de login e de rede, aviso antes das reuniões (janela, uma vez só, fila no servidor e despertar do HUD), com a API do Google falsa |
| Avisos | Horários em português ("amanhã às 10h", "daqui a 2h30", "segunda às 9") com relógio falso, `lembretes.json` entre reinícios e com trava, bateria, CPU, RAM e disco com sondas falsas, pasta Downloads falsa (parciais do Chrome e do Firefox), rota de cada prioridade com o link aberto e fechado, silêncio, assuntos silenciados, abertura do link pela via da palavra de ativação e as ferramentas de voz |
| Presença | Máquina de estados chegou e saiu com histerese, quadros e relógio falsos, boas-vindas com o resumo do tempo fora, pausa, bloqueio e embeddings do dono |
| Celular | Código de pareamento (validade, uso único, tentativas), token por aparelho só como hash, revogação (inclusive cortando o feed da câmera em andamento), todas as rotas protegidas sem token, cookie `HttpOnly`, `Secure` e `SameSite=Strict`, gerência só no PC (com DNS rebinding), certificado com Name Constraints, reemissão quando o IP muda e a palavra de ativação sem acordar o celular |
| Servidor | Formato do endpoint de token e sanitização, tela ambiente e leitura do sistema ao vivo |
| Integrações MCP | `tests/test_mcp.py` confere o `mcp.json` (token no arquivo, url sem https e campos errados recusados), o `permitir` vazio e o token faltando, quais ferramentas pedem código, a frase "confirmar integração", o filtro e os nomes com o serviço na frente, o resultado marcado como dado e no painel, a confirmação, o cancelamento, o servidor que falha ou demora e o `/api/status`. Também roda um servidor MCP falso de verdade por stdio (`tests/mcp_fake_server.py`) |

No HUD (vitest, em `web/`): o som de cada evento, o volume salvo no navegador e os estados "pensando" e "executando" do núcleo (`sounds.test.ts`, `coreActivity.test.ts`), preferências salvas (persona, qualidade, legenda) e layout dos painéis, qualidade automática da cena (só desce depois de uma lentidão seguida), o modo visual que não pisca entre os estados (`visualMode.test.ts`), a palavra ouvida e a persona que ela chama (`wake.test.ts`), o perfil de cada persona e o timbre dos sons (`themes.test.ts`), o painel Gestos (`gestures.test.ts`), tempo de resposta, modo ambiente, geometria dos gráficos, som do reator, o destaque de sintaxe o painel do assistente de tela, a marca "pelo sentido" do painel Memória, os servidores MCP no painel Protocolos e, no celular, o código do QR, o nome do aparelho, as chamadas de pareamento e revogação, a cena leve e o manifest do PWA.
