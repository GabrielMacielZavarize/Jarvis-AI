# Roteiro de testes em casa (Windows)

Checklist único de tudo que já está na `main`. Os testes automáticos ([testes.md](testes.md)) cobrem a lógica com simulações. O que está aqui só dá para conferir na máquina real: webcam, microfone, os 3 monitores, o Google, o Gemini de verdade e o celular. O passo a passo completo de cada item está na página indicada.

## 0. Preparar

```powershell
git checkout main
git pull
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python jarvis.py --rebuild
.venv\Scripts\python doctor.py
```

No `.env` (os nomes e comentários estão no `.env.example`), ligue o que for testar:

```env
JARVIS_ENABLE_PC_CONTROL=true
JARVIS_ENABLE_CAMERA=true
JARVIS_ENABLE_GESTURES=true
JARVIS_ENABLE_COMPUTER_USE=true
JARVIS_WAKE_WORD=true
JARVIS_PROACTIVE=true
JARVIS_ENABLE_CALENDAR=true      # só depois do login do Google (item 8)
JARVIS_PRESENCE=true             # veja o aviso do item 6
JARVIS_HOME_CITY=Criciúma

# Link e modelos (item 12). Se o seu .env tem JARVIS_WAKE_SILENCE_SECONDS=30, troque para 0:
# o valor do .env vale mais que o padrão do código.
JARVIS_WAKE_SILENCE_SECONDS=0
GOOGLE_FALLBACK_MODELS=gemini-3.1-flash-live-preview,gemini-2.5-flash-native-audio-preview-12-2025
JARVIS_MODEL_ROTATION=fallback
JARVIS_END_OF_SPEECH_MS=0
```

Confira no `doctor.py` a linha "Link fecha sozinho: nunca" e a lista de modelos, todos "livre". Não há dependência nova de Python, mas o `--rebuild` é obrigatório para o HUD novo. Ele também roda o `npm install` quando o `package-lock.json` mudou, para trazer as fontes novas das personas.

Teste um grupo por vez. Se algo falhar, copie a linha do terminal com a tag do protocolo (`[GST-18]`, `[MOU-20]`, `[DIT-29]`...) e, nos gestos, grave um trace com `--trace`.

## 1. Gestos: precisão e calibração

Detalhes em [gestos.md](gestos.md#precisão-e-calibração).

- [ ] `python gestures.py --calibrate`: as 6 poses terminam com acerto de 90% ou mais.
- [ ] `python gestures.py --preview --dry-run`: com a mão parada a confiança fica verde e a pose estável não pisca; punho frouxo continua `fist`.
- [ ] Segurando uma janela, tirar a mão do quadro pela lateral mostra "Cancelado" e não move nada.
- [ ] Os gestos funcionam com a mão a uns 30 cm e a 1 m da câmera.
- [ ] Mouse no ar (`m` no preview): cursor parado não treme; movimento rápido chega ao outro monitor.

## 2. Gestos personalizáveis

Detalhes em [gestos.md](gestos.md#gestos-personalizáveis).

- [ ] OK parado pausa e retoma a mídia.
- [ ] Pinça subindo e descendo muda o volume de 5 em 5%.
- [ ] Rock parado aplica o layout "modo trabalho" (salve antes: "salva esse layout como modo trabalho").
- [ ] Janela pega e 1, 2 ou 3 dedos parados: ela vai para a tela 1, 2 ou 3 do Identificar.
- [ ] Tapar a webcam por 1 s muta e desmuta o Jarvis; apagar a luz sem a mão na frente não faz nada.
- [ ] Duas palmas se afastando maximizam a janela; se aproximando, restauram.
- [ ] Por voz: "quando eu fizer joinha, pausa a música", "o que faz o rock?", "lista meus gestos"; "o rock fecha a janela" é recusado.

## 3. Painel de gestos com câmera e mapa das telas

Detalhes em [gestos.md](gestos.md#painel-de-gestos).

- [ ] "Mostra o painel de gestos" (ou dois dedos parados por 1 s): o painel aparece no canto inferior direito do notebook, com a câmera e o mapa dos 3 monitores.
- [ ] Arraste uma janela do notebook para o monitor de cima pelo mapa (punho em cima dela, mover, abrir a mão).
- [ ] Repita para o monitor vertical (à esquerda, x negativo).
- [ ] O painel não aparece nos prints do Jarvis ("o que tem na tela?").

## 4. Palavra de ativação e voz

Detalhes em [voz.md](voz.md).

- [ ] `python wake_word.py --test`: "Jarvis" passa do limiar e frases comuns não.
- [ ] Diga "Jarvis": bipe, o link abre e ele responde no tom do mordomo britânico.
- [ ] "Quais vozes você tem?" e "troca sua voz para Orus"; "volta pra sua voz normal".
- [ ] Sons do HUD (link, ferramenta, confirmação, erro, timer) e o volume em Ajustes.

## 5. Mouse, teclado e ditado

Detalhes em [mouse-e-ditado.md](mouse-e-ditado.md).

- [ ] "Abre o bloco de notas e digita olá"; Esc ou mexer no mouse cancela.
- [ ] No Bloco de Notas: "modo ditado", dite com "vírgula", "ponto de interrogação", "nova linha", "apaga a última palavra", "desfaz" e depois "fim do ditado".
- [ ] No WhatsApp Web, "nova linha" não envia a mensagem.
- [ ] "Escreve aqui: chego em 10 minutos" fora do modo ditado.

## 6. Presença pela câmera

Detalhes em [camera-e-presenca.md](camera-e-presenca.md#presença).

Os gestos ainda abrem a webcam por conta própria. Com presença e gestos ligados ao mesmo tempo, o Windows pode recusar a segunda abertura ("câmera em uso"). Teste a presença com os gestos desligados e depois os dois juntos, para ver se a sua webcam aguenta. Com `JARVIS_WAKE_SILENCE_SECONDS=0`, o link que a presença abre também só fecha com "tchau, Jarvis" ou o botão.

- [ ] (Opcional) com o Jarvis fechado: `python presence.py --enroll` e `python presence.py --test`.
- [ ] Saia da frente do PC por mais de 5 min: a mídia pausa (e o PC bloqueia, se `JARVIS_PRESENCE_LOCK=true`).
- [ ] Volte: "Bem-vindo de volta, senhor" com o resumo do tempo fora.
- [ ] O painel Sistema mostra "Presente" e "Ausente há X min".

## 7. Rotinas

Detalhes em [memoria-e-rotinas.md](memoria-e-rotinas.md#rotinas).

- [ ] "Bom dia, Jarvis": clima, manchetes, lembretes, layout de trabalho e playlist, com cada passo no painel Rotina.
- [ ] "Modo foco": pomodoro e volume baixo. "Boa noite" pergunta antes de bloquear o PC.
- [ ] "Cria uma rotina estudo que abre o Notion e põe lo-fi" e depois "roda a rotina estudo".
- [ ] "Todo dia útil às 8h roda o bom dia" (teste com um horário daqui a 2 min).

## 8. Google Agenda

Detalhes em [agenda.md](agenda.md).

- [ ] Crie as credenciais OAuth (passo a passo em [agenda.md](agenda.md#login-no-google-uma-vez-só)) e rode `python calendar_tools.py --login` e `--hoje`.
- [ ] "O que eu tenho hoje?", "e amanhã?", "qual minha próxima reunião?".
- [ ] "Marca dentista sexta às 15h": só grava com "confirmar agenda" e o código.
- [ ] Evento daqui a 12 min: uns 10 min antes o Jarvis abre o link sozinho e avisa.

## 9. Avisos e lembretes

Detalhes em [avisos.md](avisos.md).

- [ ] "Me lembra daqui a 2 minutos de beber água": com o link fechado, ele abre e avisa.
- [ ] Tire o carregador; termine um download na pasta Downloads.
- [ ] "Para de me avisar sobre bateria" e "horário de silêncio das 22h às 6h".

## 10. Assistente de tela

Detalhes em [assistente-de-tela.md](assistente-de-tela.md).

- [ ] No PowerShell, um erro de Python e "explica esse erro": causa e correção no painel.
- [ ] "O que tem de errado aqui?" com o mouse sobre o erro, inclusive no monitor vertical.
- [ ] "Copia a correção" e Ctrl+V: vem o bloco certo, e o Jarvis nunca digita sozinho.
- [ ] Com o `.env` aberto, o painel avisa que ocultou segredos.

## 11. Celular na rede de casa

Detalhes em [celular.md](celular.md).

- [ ] `python jarvis.py --lan`: o HUD do PC mostra o QR de pareamento.
- [ ] No celular, instale o certificado ([celular.md](celular.md#tirando-o-aviso-de-certificado)), pareie e fale com o Jarvis.
- [ ] Peça algo no PC pelo celular ("abre o YouTube no monitor de cima").
- [ ] Revogue o aparelho no HUD: o celular perde o acesso na hora, inclusive ao feed da câmera.

## 12. Link, modelos e tempo de resposta

Detalhes em [modelos.md](modelos.md).

- [ ] Abra o link e fique 20 min sem falar: ele continua aberto e responde na hora quando você volta (a sessão passa dos 15 min por causa da compressão de contexto).
- [ ] Converse alguns turnos: o painel Sistema mostra "Tempo de resposta" (verde até 1,5 s) com a média, e o terminal do agente registra "Resposta em X s (modelo)".
- [ ] Troca de modelo: ponha `GOOGLE_MODEL=gemini-teste-live` (não existe) e abra o link. Ele conversa pelo próximo modelo, a notificação "Modelo de reserva" aparece e o painel mostra "Modelo · reserva". `python doctor.py` lista o modelo falso "em pausa". Depois volte o `GOOGLE_MODEL` de antes.
- [ ] Depois de uma troca de modelo, "troca sua voz para Orus" continua valendo na hora.
- [ ] `JARVIS_MODEL_ROTATION=rotate`: abra e feche o link 3 vezes. O painel Sistema mostra um modelo diferente a cada link.
- [ ] (Opcional) `JARVIS_END_OF_SPEECH_MS=500` e compare o tempo de resposta; se ele cortar a sua frase, suba para 900.

## 13. Visual do HUD

Detalhes em [hud.md](hud.md).

- [ ] Boot: o anel do reator se completa, aparece "Todos os sistemas online" e os painéis entram em cascata.
- [ ] Ao processar, o HUD inteiro vai ficando âmbar aos poucos, sem piscar; numa falha, vermelho. Numa conversa de vários turnos, o núcleo e o HUD não piscam entre "processando" e "respondendo" nem nas pausas entre frases.
- [ ] "Como está o tempo em Lisboa?": a placa sobre o núcleo mostra `WX-01 · Varredura meteorológica · Lisboa` e depois "Concluído"; o painel tem o gráfico das próximas 24 h (passe o mouse).
- [ ] A legenda da fala do Jarvis aparece palavra por palavra embaixo do núcleo e some alguns segundos depois (desliga em Ajustes).
- [ ] Ajustes, Persona: as quatro mudam o nome, a marca, o núcleo 3D, os painéis, as fontes e os sons (veja o item 14).
- [ ] Modo cinema: tecla `F`, o botão ao lado do dock e "modo cinema" por voz; `Esc` ou "mostra os painéis de novo" voltam.
- [ ] "Pesquise sobre fusão nuclear": o globo cresce, os anéis recuam e cada destino ganha cidade e site.
- [ ] "Rode um diagnóstico": aparece "Ao vivo" e CPU e RAM se mexem (abra um app pesado para ver subir).
- [ ] "O que eu tenho hoje?" (com a agenda ligada): o dia em blocos, com o marcador de agora; passe o mouse nos blocos.
- [ ] Notificações à direita: um timer de 1 min acabando, um lembrete do item 9 e um download concluído.
- [ ] Arraste o painel Registro pelo cabeçalho para a coluna da esquerda; F5 e ele continua lá; "Restaurar painéis" em Ajustes desfaz.
- [ ] Modo ambiente: feche o link e não mexa em nada por 3 min. Aparecem o relógio grande, o clima da `JARVIS_HOME_CITY` e a próxima reunião. Mexer o mouse ou dizer "Jarvis" volta ao HUD.
- [ ] Ajustes, Qualidade: mostra o nível e os fps. Em "Automática", num PC mais fraco, ela desce sozinha depois de uns 8 s lenta, e o Registro diz "Qualidade da cena: Média (32 fps)".
- [ ] Ajustes, Som do reator: com o link aberto, o zumbido cresce quando o Jarvis fala.
- [ ] No celular pareado (item 11): tema, legenda e modo cinema funcionam; os painéis não se arrastam no celular, de propósito.

## 14. Personas

Detalhes em [hud.md](hud.md#o-que-cada-persona-muda).

- [ ] Ajustes, Persona, F.R.I.D.A.Y. com o link fechado: o boot, a marca e o nome na barra mudam. Abra o link: ela cumprimenta ("Boa noite, chefe. F.R.I.D.A.Y. na escuta...") com voz feminina (Kore) e a transcrição mostra "F.R.I.D.A.Y.".
- [ ] Com o link aberto, "Jarvis, modo Mark III": ele confirma na voz atual, a conversa fica quieta um instante e o Mark III se apresenta em outra voz (Orus). A holografia se rematerializa com o reator arc e a mira. Pergunte o clima: a resposta vem curta, de relatório.
- [ ] Clique em Stealth no meio da conversa: sem partículas e sem brilho, sons baixinhos, voz sussurrada e respostas de uma frase.
- [ ] "Troca sua voz para Aoede" com a F.R.I.D.A.Y.; volte ao J.A.R.V.I.S. (continua a voz dele) e de novo à F.R.I.D.A.Y. (Aoede).
- [ ] Abra o HUD no celular pareado: ele mostra a mesma persona do PC.
- [ ] O `persona.json` aparece ao lado do projeto e não entra no `git status`.

## 15. Gestos no HUD

Detalhes em [gestos.md](gestos.md#gestos-no-hud).

- [ ] Com `JARVIS_ENABLE_GESTURES=true`, o painel Gestos aparece na coluna da direita. Sem link, os botões ficam apagados e o editor funciona.
- [ ] Abra o link e clique em Ligar: aparece "Abrindo a câmera…" e depois "Armados". Mão aberta, punho, mova e abra: o painel mostra a janela segura e o monitor de destino, e depois o resultado.
- [ ] Mouse no ar e Painel da câmera pelos botões ligam e desligam. O estado acompanha também quando você usa os próprios gestos (dois dedos parados abrem o painel da câmera).
- [ ] Editar, rock, Abrir app, `spotify`, Salvar. Faça o rock: o Spotify abre sem reiniciar nada.
- [ ] Editar, OK, Atalho, `alt+f4`, Salvar: é recusado com a explicação e nada muda no `gestos.json`.
- [ ] Ligue o joinha a "tocar/pausar": o painel avisa que ele faz o mesmo que o OK. "Restaurar todos" volta tudo ao padrão.

## 16. Memória pelo sentido

Detalhes em [memoria-e-rotinas.md](memoria-e-rotinas.md#busca-pelo-sentido).

- [ ] "Lembra que eu trabalho no Jarvis-AI à noite" e "lembra que eu prefiro lo-fi pra programar". O `memoria_vetores.json` aparece ao lado do projeto e não entra no `git status`.
- [ ] "O que eu te falei do meu projeto?": o Jarvis responde com o Jarvis-AI e o painel Memória mostra "pelo sentido" com a nota.
- [ ] "Do que eu gosto de ouvir?": vem o lo-fi. "Qual a capital da França?": nenhuma memória entra no painel.
- [ ] `python memory.py --busca "do que eu gosto de ouvir?"` mostra as notas. Anote as das memórias certas e das sem relação; se ficarem perto do 0.6, ajuste `JARVIS_MEMORY_MIN_SIMILARITY`.
- [ ] "Esquece o que eu falei do lo-fi": a memória e o vetor dela somem (o id não aparece mais no `memoria_vetores.json`).
- [ ] Desligue a internet e pergunte "qual é a minha reunião?": a busca por palavras responde normal.

## 17. Uma palavra por persona

Detalhes em [voz.md](voz.md#uma-palavra-por-persona). Precisa do modelo treinado em `.cache/models/friday.onnx`.

- [ ] Sem o arquivo e com `JARVIS_WAKE_WORDS=jarvis,friday`: o terminal e o `doctor.py` avisam que a "Friday" ficou de fora, e "Jarvis" acorda a persona que estiver na tela, como antes.
- [ ] Com o arquivo: o painel Sistema mostra "Aguardando “Jarvis” ou “Friday”". `python wake_word.py --test` mostra uma coluna por palavra.
- [ ] HUD no J.A.R.V.I.S., diga "Friday": o tema troca, o Registro mostra "Persona · F.R.I.D.A.Y., chamada pelo nome" e ela cumprimenta com "chefe" na voz Kore.
- [ ] Com a F.R.I.D.A.Y. ativa, diga "Jarvis": volta para o J.A.R.V.I.S. Com o Mark III ativo, "Jarvis" mantém o Mark III.
- [ ] Música e TV em inglês por 10 minutos com o `--test` aberto: anote quantas vezes a "Friday" ativaria e ajuste o `JARVIS_WAKE_THRESHOLD_FRIDAY`.

## 18. Apontar e falar

Detalhes em [gestos.md](gestos.md#apontar-e-falar). Precisa dos gestos, do controle do PC e do link aberto.

- [ ] Erro no monitor vertical, mouse parado no notebook: aponte para o erro e diga "explica isso aqui". O painel diz "texto onde você apontou" e explica o erro certo.
- [ ] A mira aparece onde a mão aponta e some cerca de 1 s depois de baixar a mão. Ela não aparece num print (`look_at_screen`).
- [ ] O cursor não se mexe nem clica enquanto você aponta e fala.
- [ ] Sem apontar, "explica isso aqui" usa o cursor. Calado, o indicador parado liga o mouse no ar.

## 19. Integrações MCP

Detalhes em [integracoes.md](integracoes.md). Precisa de `JARVIS_ENABLE_MCP=true`, do `mcp.json` e de um token do GitHub no `.env`.

- [ ] `python mcp_client.py` mostra o GitHub conectado e as ferramentas liberadas. O `mcp.json` não entra no `git status`.
- [ ] O painel Protocolos mostra o MCP-32 com o GitHub e as ferramentas.
- [ ] "Quais issues abertas eu tenho no Jarvis-AI?": a placa mostra "MCP-32 · GitHub · list_issues" e o painel lista as issues.
- [ ] Uma ferramenta fora do `permitir` não aparece no `mcp_status` nem é chamada.
- [ ] Com `create_issue` liberada, "cria uma issue chamada teste": nada é criado antes de "confirmar integração" e o código.
- [ ] Sem o token no `.env`, o link abre normal e o Jarvis diz que a integração está indisponível.

## 20. Ferramentas sob demanda

Detalhes em [ferramentas-sob-demanda.md](ferramentas-sob-demanda.md). Ligue tudo no `.env` (PC, mouse, agenda, email, câmera, gestos, avisos e MCP) e deixe `JARVIS_TOOL_ROUTING=auto`.

- [ ] O terminal do agente não mostra nenhum grupo carregado ao abrir o link. "Que horas são?" responde direto, sem "Um instante.".
- [ ] "O que eu tenho hoje?": ele diz "Um instante.", a placa mostra "FER-33 · Carregando ferramentas · Agenda" e logo depois vem a agenda sem você repetir. Anote quanto tempo passa entre o "Um instante." e a resposta.
- [ ] Na mesma conversa, "e amanhã?": responde direto, sem "Um instante." de novo.
- [ ] "Abre o Spotify e põe o volume em 30": um "Um instante." só, para janelas e mídia juntas.
- [ ] "Marca dentista sexta às 15h", depois peça janelas, mídia, mouse e tela antes de confirmar. Diga "confirmar agenda" e o código: o evento é criado.
- [ ] "Quais issues abertas eu tenho no Jarvis-AI?": o GitHub conecta só agora (veja o terminal) e a lista aparece.
- [ ] Peça a agenda e faça o Gemini cair (cota ou um modelo inválido no `GOOGLE_MODEL`): no modelo de reserva, "e amanhã?" responde sem pedir o grupo de novo.
- [ ] Repita os pedidos com `JARVIS_TOOL_ROUTING=false`: nenhum "Um instante." e tudo funciona como antes. Compare quantas vezes ele escolheu a ferramenta errada nos dois modos.
- [ ] Com o `.env` padrão (só memória e rotinas) e `auto`: nada muda em relação a antes.
