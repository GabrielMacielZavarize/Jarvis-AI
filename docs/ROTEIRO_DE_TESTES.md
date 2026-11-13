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

- [ ] "Bom dia, Jarvis": cumprimento, briefing do dia, layout de trabalho e playlist, com cada passo no painel Rotina (detalhes na seção 33).
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
- [ ] Com o `.env` padrão (memória, diário e rotinas) e `auto`: nada muda em relação a antes.

## 21. Casa inteligente

Detalhes em [casa.md](casa.md). Precisa de `JARVIS_ENABLE_MCP=true`, da integração Model Context Protocol Server no Home Assistant, da entrada `home_assistant` no `mcp.json` e do `HOME_ASSISTANT_TOKEN` no `.env`.

- [ ] `python mcp_client.py` mostra o Home Assistant conectado. `HassTurnOn` aparece com "pede código se mexer em porta, fechadura, portão, alarme ou câmera". Se algum nome do `permitir` não existir, acerte pelo que ele lista.
- [ ] "Apaga a luz do escritório": a placa mostra "MCP-32 · Home Assistant · HassTurnOff" e a luz apaga sem código.
- [ ] "Liga o ar da sala" e "deixa a luz da sala em 40%" rodam sem código.
- [ ] "A porta da frente está trancada?": o Jarvis responde pelo `GetLiveContext`, sem código.
- [ ] "Destranca a porta da frente": nada acontece antes de "confirmar integração" e o código. Teste também "cancela".
- [ ] "Abre o portão da garagem" e "desliga o alarme" pedem código, mesmo com `HassTurnOn` e `HassTurnOff` em `sem_confirmar`.
- [ ] Com a url em `http://homeassistant.local:8123/api/mcp`, o `python mcp_client.py` recusa o `mcp.json` e pede o IP ou `https://`.
- [ ] Sem o token no `.env`, o link abre normal e o Jarvis diz que a integração do Home Assistant está indisponível.

## 22. Fica de olho no terminal

Detalhes em [assistente-de-tela.md](assistente-de-tela.md#fica-de-olho-numa-janela). Precisa de `JARVIS_ENABLE_PC_CONTROL=true`, `JARVIS_PROACTIVE=true` e da `GOOGLE_API_KEY`.

- [ ] O painel Protocolos mostra o OLH-35. "Fica de olho no terminal" com o Windows Terminal aberto atrás do HUD: ele confirma e diz qual terminal.
- [ ] Rode `python -c "1/0"` no terminal. Até uns 10 s depois o Jarvis diz que apareceu um erro e pergunta se quer a explicação. "Sim": o painel Assistente de tela explica o `ZeroDivisionError`, com o terminal ainda atrás do HUD.
- [ ] Rode o mesmo comando de novo: nenhum aviso novo. Rode `python -c "import json; json.loads('{')"`: vem aviso do `JSONDecodeError`.
- [ ] Um teste falhando (`pytest` ou `phpunit`) e um `npm run build` quebrado também avisam. Abrir um arquivo com `catch (Exception $e)` no PhpStorm vigiado não avisa nada.
- [ ] "Fica de olho no PhpStorm" e depois "que janela você está vigiando?": ele diz o PhpStorm, os minutos e os erros avisados.
- [ ] Encerre o link e provoque outro erro: aparece só o aviso no HUD, com o código OLH-35 e "sem voz".
- [ ] "Para de me avisar dos erros" silencia o assunto: com o link aberto o próximo erro fica só no HUD. "Pode voltar a avisar dos erros" desfaz.
- [ ] Imprima uma chave falsa no erro (`python -c "raise RuntimeError('AIzaSyA1234567890abcdefghijklmnopqrstu')"`): nem o aviso nem o painel mostram a chave.
- [ ] Feche o terminal vigiado: aparece no HUD que o vigia parou porque a janela fechou. Deixe outro vigia 30 minutos parado: ele para sozinho.
- [ ] "Fica de olho no KeePass" é recusado. "Para de vigiar" desliga, e o Gerenciador de Tarefas mostra o `jarvis.py` sem gasto de CPU perceptível enquanto vigia.

## 23. Diário das conversas

Detalhes em [diario.md](diario.md). Precisa da `GOOGLE_API_KEY` e de `JARVIS_DIARY=true` (o padrão).

- [ ] Converse uns minutos sobre um assunto (um bug do Jarvis-AI, por exemplo), deixe algo para depois e encerre o link. O `diario.json` aparece ao lado do projeto, com a entrada de hoje, e não entra no `git status`.
- [ ] Abra o link, pergunte só "que horas são?" e encerre: nenhuma entrada nova.
- [ ] Abra de novo: "o que eu te pedi hoje?" responde com o pedido e o pendente, e o painel Diário mostra a conversa no dia.
- [ ] "Onde paramos no projeto do Jarvis?" acha a conversa mesmo sem as mesmas palavras, com "pelo sentido" no painel.
- [ ] Diga uma senha falsa na conversa ("minha senha do wifi é teste123") e encerre: ela não aparece no `diario.json`.
- [ ] "Esquece essa conversa" e encerre: nenhuma entrada nova. "Apaga o diário de hoje": as de hoje somem. O × do painel apaga uma só, depois do "Apagar?".
- [ ] Com `JARVIS_DIARY=false`, encerre uma conversa longa: nada é gravado e o painel Protocolos não mostra o DIA-36.

## 24. Rotinas por contexto

Detalhes em [memoria-e-rotinas.md](memoria-e-rotinas.md#por-contexto). Precisa de `JARVIS_ENABLE_PC_CONTROL=true`. Para chegar e sair, também da presença.

- [ ] Com o PhpStorm fechado, "quando eu abrir o PhpStorm, roda o modo foco". Abra o PhpStorm sem aba do HUD: o navegador abre, o painel Rotina mostra "por contexto" e o Jarvis diz que rodou porque o PhpStorm abriu.
- [ ] Com a conversa aberta, feche e abra o PhpStorm depois de 30 minutos: a rotina roda na conversa, sem abrir outro link. Antes disso, nada acontece.
- [ ] Reinicie o `python jarvis.py` com o PhpStorm já aberto: nada dispara.
- [ ] "Quando o Spotify ficar em foco, roda o lo-fi": trocar de janela para o Spotify dispara uma vez.
- [ ] "Quando eu conectar o fone, roda o modo foco": ligue o fone Bluetooth e espere até 15 segundos.
- [ ] Com a presença ligada, "quando eu sair, roda a boa noite": saia da frente da câmera; o Jarvis pergunta antes de bloquear e nada é bloqueado sem o seu "sim".
- [ ] "Quando o PC entrar na rede (nome da sua rede), roda o bom dia": desconecte e reconecte o Wi-Fi.
- [ ] "Desliga o gatilho do modo foco" e abra o PhpStorm: nada acontece. Com `JARVIS_CONTEXT_TRIGGERS=false`, nenhum gatilho dispara e o `/api/status` mostra 0 em `context_triggers`.
- [ ] Uma rotina que abre a Steam não dispara uma segunda rotina presa à Steam (intervalo de 90 segundos).

## 25. Clica aqui apontando

Detalhes em [mouse-e-ditado.md](mouse-e-ditado.md#clica-aqui-apontando). Precisa de `JARVIS_ENABLE_COMPUTER_USE=true`, dos gestos armados e do link aberto.

- [ ] Vídeo do YouTube pausado no monitor vertical, mouse parado no notebook. Aponte para o play e diga "Jarvis, clica aqui". A mira fica parada no play com "CLICANDO AQUI", o cursor desliza até ela e o vídeo toca. O terminal não mostra consulta ao modelo de visão.
- [ ] O painel MOU-20 mostra o print da tela certa com a mira laranja em cima do play.
- [ ] Baixe a mão logo depois de falar: o clique ainda sai no ponto e a mira continua até o clique.
- [ ] Aponte para o botão Enviar de um email ou do WhatsApp e diga "clica aqui": nada é clicado, a mira fica com "CONFIRMAR CLIQUE AQUI?" e o Jarvis pede "confirmar clique" e o código. Com o código, o clique sai no mesmo ponto.
- [ ] Aponte para o HUD, para uma janela do UAC ou do Gerenciador de Tarefas e diga "clica aqui": recusado, sem mexer no cursor.
- [ ] Num jogo ou vídeo em tela cheia, "clica aqui" pede o código (o Jarvis diz que não conseguiu ler o ponto).
- [ ] Aponte para a busca do YouTube e diga "digita lo-fi aqui": o Jarvis clica na busca e digita nela. Apontando para o meio da página, ele recusa e nada é digitado.
- [ ] Aponte para a caixa de mensagem do WhatsApp e diga "escreve aqui: já vou". O texto cai na caixa apontada, mesmo com outra janela em foco antes, e nada é enviado.
- [ ] Aponte para um campo de senha e diga "digita olá aqui": recusado.
- [ ] Sem apontar, "clica no botão de play" e "digita olá" funcionam como antes.

## 26. CI no GitHub Actions

Detalhes em [testes.md](testes.md#ci-no-github-actions).

- [ ] Depois do push, a aba Actions mostra os três jobs (pytest, vitest e build do HUD, testes visuais do HUD) verdes.
- [ ] Um pull request mostra os três jobs como checks.
- [ ] A segunda execução usa o cache do pip, do npm e do modelo do MediaPipe (o passo de cache diz "Cache restored").
- [ ] No Windows, `npm run e2e` em `web/` passa com `JARVIS_PYTHON=python` e não troca a persona que estava escolhida.

## 27. Painel de saúde

Detalhes em [saude.md](saude.md).

- [ ] Converse alguns turnos. O painel Saúde (SAU-40) mostra o tempo de resposta e o `saude.db` aparece na pasta do projeto, fora do `git status`.
- [ ] Diga "Jarvis" e fique calado até o link fechar por silêncio, três vezes. Em Detalhes, a linha do Jarvis mostra 3 sem fala e a sugestão pede para subir `JARVIS_WAKE_THRESHOLD_JARVIS`.
- [ ] Diga "Jarvis" baixinho, longe do microfone, algumas vezes sem ativar. As quase ativações sobem.
- [ ] Peça o clima de uma cidade inventada até a ferramenta falhar. Ela aparece em Ferramentas com erro.
- [ ] No celular pareado o painel aparece sem o botão Limpar. No PC, Limpar zera tudo.
- [ ] Com `JARVIS_HEALTH=false` o painel mostra "desligado" e nada novo é gravado.

## 28. Ícone na bandeja

Detalhes em [bandeja.md](bandeja.md). Só no Windows.

- [ ] `pythonw jarvis.py --tray`: nenhuma janela de terminal abre, o ícone aparece ao lado do relógio e o HUD abre no navegador. O ícone fica cinza e depois azul em poucos segundos.
- [ ] Pare o mouse sobre o ícone: a dica mostra servidor, agente e link. Com `JARVIS_WAKE_WORD=true`, o centro do ícone acende e a dica diz "Palavra de ativação: ouvindo".
- [ ] Botão direito, Iniciar o link: o HUD toca o som de ativação, o Registro mostra "Bandeja · abrindo o link" e o ícone fica verde. Feche a aba antes e repita: o navegador abre e conecta sozinho.
- [ ] Com o link aberto, Encerrar o link: o link fecha, o Registro mostra "Bandeja · link encerrado" e o ícone volta ao azul. Sem link aberto, o item vira Iniciar o link de novo.
- [ ] Com `JARVIS_ENABLE_GESTURES=true`, Gestos: a webcam liga, aparece a notificação e o item fica marcado. De novo: a webcam apaga.
- [ ] Iniciar com o Windows: o item fica marcado e a entrada `Jarvis` aparece em Configurações, Aplicativos, Inicialização. Saia da conta e entre de novo: o ícone aparece sem terminal e sem abrir aba nova. Desmarque e confira que a entrada sumiu.
- [ ] Abrir a pasta de logs: o `jarvis.log` tem as linhas `[jarvis]`, `[jarvis.agente]` e `[jarvis.ativacao]`. A pasta `logs` não entra no `git status`.
- [ ] Reiniciar o Jarvis: o ícone some e volta em alguns segundos, sem aba nova no navegador, e o HUD aberto reconecta.
- [ ] Mate o processo do agente pelo Gerenciador de Tarefas: o ícone fica amarelo e a dica diz "Agente: parado".
- [ ] Reinicie o Explorer pelo Gerenciador de Tarefas: o ícone volta sozinho.
- [ ] Sair: o ícone some e não sobra nenhum `pythonw.exe` do Jarvis no Gerenciador de Tarefas. A webcam e o microfone ficam livres.
- [ ] Com 125% ou 150% de escala no Windows, o ícone fica nítido.

## 29. HUD novo: áreas, paleta e briefing

Detalhes em [hud.md](hud.md).

- [ ] As abas no topo trocam entre Painel, Dia a dia, Olho de Deus, Sistema e Ajustes; as teclas `1` a `5` fazem o mesmo e `Esc` volta ao Painel.
- [ ] `Ctrl+K` abre a paleta. Digite "mark" e Enter: a persona troca. Com o link aberto, digite uma pergunta e Enter: ela vai por texto ao Jarvis.
- [ ] O Briefing mostra a saudação, o clima da `JARVIS_HOME_CITY` e a próxima reunião. Peça o clima por voz: o Briefing encolhe para uma linha e a projeção aparece logo abaixo.
- [ ] Peça três ou quatro coisas seguidas (clima, diagnóstico, um timer, uma pesquisa): a coluna da esquerda rola e nenhum painel fica cortado.
- [ ] Diminua a janela do navegador até virar uma coluna só: as abas descem para a barra de baixo e nada rola de lado.
- [ ] No celular pareado: o botão Inicializar aparece inteiro, a barra de baixo troca de área e a conversa fica logo abaixo do núcleo.
- [ ] Com as quatro personas, confira que as abas, a paleta e o Briefing seguem as cores e as formas de cada uma.

## 30. Olho de Deus

Detalhes em [olho-de-deus.md](olho-de-deus.md). Os testes automáticos usam respostas falsas das fontes: é aqui que se confere contra os serviços de verdade.

- [ ] Área Olho de Deus (tecla `3`), digite `8.8.8.8`: o aviso diz "Reconhecido como IP" e o resultado traz Estados Unidos, Google e um globo pequeno. No Painel, o globo 3D desenha um arco até lá.
- [ ] Campo vazio com o tipo IP escolhido: aparece o seu IP público e o seu provedor.
- [ ] `github.com`: registro (criado em 2007), DNS, SPF e DMARC, certificado válido e uma lista de subdomínios. Se o crt.sh estiver lento, o resto aparece sem os subdomínios.
- [ ] Um link encurtado (`bit.ly/...`) de um site conhecido: "Caminho do link" mostra o redirecionamento e o veredito é verde ou de atenção.
- [ ] `http://192.168.0.1` e `http://localhost:8000`: o resultado diz que não conecta na rede local, e nada chega ao roteador nem ao próprio HUD.
- [ ] O CNPJ `00.000.000/0001-91`: Banco do Brasil, situação ativa. Um CNPJ com um dígito trocado é recusado na hora, sem ir à rede.
- [ ] O CEP `01310-100` (Avenida Paulista) e o DDD `48`.
- [ ] O seu email: a lista de vazamentos, ou "não apareceu em vazamentos conhecidos".
- [ ] Em "Senha vazada?", digite `password`: aparece que vazou milhões de vezes e o campo esvazia. Na aba Rede das ferramentas do navegador, o pedido é `/api/osint/pwned/5BAA6`, só com 5 caracteres.
- [ ] O seu nome de usuário do GitHub: aparece em "Perfis encontrados", com link.
- [ ] Um CPF (`123.456.789-09`) e um telefone com DDD: o botão Consultar desliga e o aviso explica que dados pessoais não são consultados.
- [ ] Por voz: "Jarvis, de onde é o IP 1.1.1.1?" projeta o painel Olho de Deus e ele fala o resumo. "Consulta o CPF tal" é recusado.
- [ ] "Minha rede" aparece apagado. Com `JARVIS_OSINT_NETWORK=true` e o Jarvis reiniciado, o botão mostra o IP público, as portas abertas (a 8000 do HUD entre elas) e os aparelhos do Wi-Fi.
- [ ] `Ctrl+K`, digite um domínio: a primeira opção é "Consultar Domínio", e Enter abre a área com o resultado.
- [ ] Com `JARVIS_ENABLE_OSINT=false`, a área mostra "Olho de Deus desligado" e o Jarvis não tem a ferramenta.

## 31. Dia a dia

Detalhes em [dia-a-dia.md](dia-a-dia.md). As cotações, as manchetes e o teste de rede só foram testados com respostas falsas: é aqui que se confere de verdade.

- [ ] "Jarvis, tenho que fechar o relatório até sexta" e "anota aí: comprar café": o painel Tarefas projeta a lista e o `tarefas.json` aparece na pasta do projeto, fora do `git status`.
- [ ] "O que falta hoje?": ele lê as tarefas numeradas. "Já fiz a segunda": a tarefa some das abertas e aparece riscada.
- [ ] Na área Dia a dia (tecla `2`), marque uma tarefa com o mouse, escreva outra no campo e apague uma nota no X. Recarregue a página: tudo continua igual.
- [ ] "Anota aí: a senha do banco é 1234" é recusado com a explicação.
- [ ] "Como está o meu dia?": o painel Briefing traz clima, próxima reunião, tarefas, lembretes, cotações e manchetes, e ele fala o resumo. O Briefing do Painel mostra o mesmo.
- [ ] "Quanto está o dólar?" e "quanto dá 150 dólares em reais?": os valores batem com um site de câmbio. "10 milhas em quilômetros" responde 16,09 sem abrir painel.
- [ ] "Começa um foco de 1 minuto com pausa de 1, dois blocos": a contagem aparece no painel Foco e na barra do topo. Deixe o link fechar por silêncio: a contagem continua e, na troca, tocam o som e a notificação "Hora da pausa". Feche também a aba do HUD: veja o item de bandeja em [Foco integrado](#foco-integrado-com-presença-avisos-e-bandeja).
- [ ] Com o foco rodando, recarregue a página: a contagem volta de onde estava. "Quanto falta do foco?" e "encerra o foco" funcionam por voz.
- [ ] "Como está a minha internet?": em uns 15 segundos ele fala download, upload e latência, e o painel Rede ganha uma barra no histórico. Peça de novo na hora: ele pede para esperar.
- [ ] No celular pareado, o painel Rede mostra o histórico sem o botão "Medir agora".
- [ ] Com `JARVIS_ENABLE_DAY=false`, a área mostra "Dia a dia desligado" e o Jarvis não tem essas ferramentas.

## 32. Pedidos parecidos: o prompt das ferramentas novas

Detalhes em [dia-a-dia.md](dia-a-dia.md#como-o-jarvis-escolhe) e [olho-de-deus.md](olho-de-deus.md). Os testes automáticos só conferem o texto do prompt; quem escolhe a ferramenta é o Gemini, então é aqui, falando de verdade, que se vê se ele acerta. Anote o que ele fez no Registro (a placa de cada ferramenta) e no painel que abriu. Com `JARVIS_PROACTIVE=true` e a agenda ligada para os itens que dependem delas.

Nota, tarefa, fato e lembrete:

- [ ] "Jarvis, anota aí: ideia de um painel de consumo." Vira nota (`add_note`), aparece em Notas no Dia a dia e NÃO aparece na Memória.
- [ ] "Tenho que fechar o relatório até sexta." Vira tarefa com prazo na sexta (`add_task`), sem lembrete criado.
- [ ] "Lembra que eu prefiro lo-fi pra programar." Vira memória (`remember`), não nota nem tarefa.
- [ ] "Anota que eu sou alérgico a dipirona." Vira memória, não nota (fato sobre você).
- [ ] "Me lembra às 15h de ligar pro contador." Vira lembrete (`set_reminder`), repete o dia e a hora e não cria tarefa. Confira com "quais lembretes eu tenho?".
- [ ] "Tenho que ligar pro contador amanhã às 10h e quero ser avisado." Vira só um lembrete para as 10h; peça "e põe na lista também" e só então nasce a tarefa.
- [ ] "Daqui a 10 minutos me avisa." Vira timer (`set_timer`), não lembrete.
- [ ] "Põe na lista: comprar café." e "guarda essa ideia: presente pro Pedro." Tarefa e nota, respectivamente.
- [ ] Com `JARVIS_ENABLE_MEMORY=false`: "anota que eu moro em Criciúma" vira nota, sem tentar `remember`. Com `JARVIS_PROACTIVE=false`: "me lembra às 15h" ele diz que não consegue avisar numa hora marcada e oferece a tarefa.
- [ ] Com as ferramentas sob demanda ligadas (`JARVIS_TOOL_ROUTING=true`): "anota aí..." funciona na primeira vez, sem "Um instante." (tarefas e notas ficam no núcleo); "me lembra às 15h..." carrega o grupo de lembretes antes.

Foco, timer e rotina:

- [ ] "Começa um foco de 25 minutos." e "um pomodoro." Abrem a sessão de foco (painel Foco e barra do topo).
- [ ] "Modo foco." Roda a rotina "modo foco" (minimiza janelas, baixa o volume, põe o timer), sem abrir a sessão. Com `JARVIS_ENABLE_ROUTINES=false`, abre a sessão de foco.
- [ ] "Modo cinema." Esconde os painéis. "Modo foco" nunca esconde os painéis quando a rotina existe.
- [ ] "Põe um timer de 25 minutos." Só o timer, sem sessão de foco.
- [ ] "Quanto falta do foco?", "pula esse bloco" e "encerra o foco" falam do foco, não de um timer.

Briefing, agenda e rotina "bom dia":

- [ ] "Como está o meu dia?" Abre o briefing.
- [ ] "O que eu tenho hoje?" Com a agenda ligada, lê a agenda; sem ela, abre o briefing. "O que falta hoje?" lê as tarefas.
- [ ] "Bom dia, Jarvis." Roda a rotina "bom dia", não o briefing.

Cotação, conversão e internet:

- [ ] "Quanto está o dólar?" e "quanto dá 150 dólares em reais?" Usam a cotação (confira num site de câmbio).
- [ ] "Quantos quilômetros são 10 milhas?" e "100 fahrenheit em celsius." Respondem na hora, sem painel. Repita com o Wi-Fi desligado: continuam respondendo. "2 libras em reais" é moeda; "2 libras em quilos" é peso.
- [ ] "Minha internet está lenta?" Mede (uns 15 s) e fala download, upload e latência; não abre o Olho de Deus. "Qual é o meu IP?" e "como está a minha rede?" não fazem o teste de velocidade.

Olho de Deus:

- [ ] "De onde é o IP 8.8.8.8?" e "esse link é golpe? bit ponto ly barra abc." Consultam; no segundo ele repete o link montado antes de consultar, se ficar em dúvida.
- [ ] "Consulta o CPF 123.456.789-09 do João." e "qual o telefone da Maria Silva de Criciúma?" Recusa em uma frase, sem chamar a ferramenta (nenhuma placa de Olho de Deus no Registro), oferecendo CNPJ, CEP, DDD, domínio, IP ou link.
- [ ] "O email fulano@exemplo.com apareceu em vazamento?" (de outra pessoa) é recusado; "meu email apareceu em vazamento?" consulta.
- [ ] "Minha senha vazou? É 123456." Ele não repete a senha, não consulta e manda você ao painel "Senha vazada?" da área Olho de Deus (tecla `3`).
- [ ] Com `JARVIS_OSINT_NETWORK=false`: "como está a minha rede?" ele diz que a consulta está desligada e não insiste.
- [ ] Com `JARVIS_ENABLE_OSINT=false` e `JARVIS_ENABLE_DAY=false` (reinicie): ele não conhece mais essas ferramentas e diz com franqueza que não consegue, sem inventar resultado.

## 33. Briefing na rotina "bom dia"

Detalhes em [memoria-e-rotinas.md](memoria-e-rotinas.md#o-passo-briefing) e [dia-a-dia.md](dia-a-dia.md#no-bom-dia). Os testes automáticos usam o servidor do HUD falso; aqui você confere com o servidor, o clima, a agenda e as notícias de verdade. Comece sem `rotinas.json` (apague ou renomeie o seu antes, guardando uma cópia).

Rotina de fábrica:

- [ ] "Bom dia, Jarvis." O painel Rotina mostra 4 passos (Cumprimento, Briefing do dia, Layout, YouTube) e o painel Briefing abre sozinho com clima, reunião, tarefas, lembretes, cotações e manchetes.
- [ ] O Jarvis fala o cumprimento e o resumo (clima, reunião, tarefas, lembretes e 2 ou 3 manchetes) sem ler a lista inteira, e as janelas voltam ao lugar e a playlist abre.
- [ ] O que ele fala bate com o painel Briefing do Painel (tecla `1`) e com "como está o meu dia?".
- [ ] Crie um lembrete para daqui a 1 hora e uma tarefa para hoje; repita o bom dia e confira que os dois aparecem no resumo falado.
- [ ] Com a agenda ligada e uma reunião hoje, a próxima reunião entra no resumo.

HUD fora do ar:

- [ ] Com o link conectado, derrube só o servidor do HUD (por exemplo, com um `JARVIS_HUD_URL` errado só para o agente) e diga "bom dia". O passo Briefing do dia aparece como falhou ("o servidor do HUD não respondeu ao briefing"), o layout e a playlist rodam mesmo assim e o Jarvis diz o que falhou, sem inventar o resumo.

Dia a dia desligado:

- [ ] Com `JARVIS_ENABLE_DAY=false` (reinicie): "bom dia, Jarvis" ainda funciona. O passo Briefing do dia fala que o briefing está desligado e usa clima, notícias e lembretes (confira que o clima é o da `JARVIS_HOME_CITY`). Não abre o painel Briefing.
- [ ] Ainda com `JARVIS_ENABLE_DAY=false` e sem internet: o passo falha de vez com a mensagem que cita `JARVIS_ENABLE_DAY=false`, e o resto da rotina segue.

Rotinas que você já tinha:

- [ ] Com um `rotinas.json` antigo (o "bom dia" com clima, notícias e lembretes), diga "bom dia, Jarvis": ele roda os 6 passos antigos, sem briefing. Peça "cria uma rotina estudo que abre o Notion" e abra o `rotinas.json`: o "bom dia" continua com os passos antigos.
- [ ] "Muda a rotina bom dia para cumprimento, briefing, layout trabalho e a playlist lo-fi." Depois "bom dia, Jarvis" usa o briefing.
- [ ] "Cria uma rotina cedo que dá o briefing e abre o Notion" e "roda a rotina cedo": o briefing é falado e o Notion abre. "Quais rotinas eu tenho?" mostra "Briefing do dia" nos passos.
- [ ] "Todo dia útil às 8h roda o bom dia" (horário daqui a 2 minutos, com o link fechado): o navegador abre, o Jarvis fala o briefing e o painel Briefing aparece.

## Dependências travadas e auditoria

Detalhes em [instalacao.md](instalacao.md#dependências-e-versões-travadas) e [testes.md](testes.md#auditoria-das-dependências). Os testes automáticos conferem o lock e o CI audita; aqui você confere o Windows de verdade e o CI no GitHub.

- [ ] Num `.venv` novo no Windows (`py -3.12 -m venv .venv`), `python -m pip install -r requirements.txt` termina sem erro (confira principalmente `mediapipe`, `opencv-contrib-python`, `pycaw`, `comtypes` e `openwakeword`, que têm roda nativa por sistema) e `python -m pip check` diz "No broken requirements found".
- [ ] `python doctor.py` e `python jarvis.py` sobem como antes: o HUD abre, o "Jarvis" ativa e a voz responde (uma troca de falas basta).
- [ ] Com a agenda, o volume (pycaw) e a palavra de ativação ligados, nada reclama de pacote faltando ou de versão.
- [ ] Depois de um `git pull` que mexeu no `package-lock.json`, o `python jarvis.py` roda o `npm install` sozinho e recompila o HUD.
- [ ] No GitHub, a aba Actions mostra os jobs `pip-audit (ubuntu-latest)`, `pip-audit (windows-latest)` e `npm audit` verdes. Um Dependabot em `Insights > Dependency graph > Dependabot` aparece com pip, npm e github-actions.
- [ ] Um PR de teste que adiciona uma linha em `requirements.in` sem regenerar o `requirements.txt` faz o passo "Lock em dia" falhar.

## Fontes externas (doctor --fontes)

Os testes automáticos usam respostas falsas; aqui você consulta os serviços de verdade, no seu PC. Detalhes em [problemas.md](problemas.md#uma-fonte-externa-falha-no-doctor---fontes).

- [ ] `python doctor.py --fontes` roda sem `.env` e mostra uma linha por fonte, em cinco grupos (Olho de Deus, Perfis de usuário, Cotações, Clima, Internet). Anote quais deram `FALHA` ou `sem rede`.
- [ ] Olho de Deus: ipwho.is, dns.google, rdap.org, BrasilAPI (CNPJ, CEP e DDD) e Pwned Passwords dão `ok`. Se alguma der `FALHA`, o motivo diz qual campo a leitura não achou: esse é o formato que mudou (ou que foi escrito errado, já que essas consultas nasceram sem acesso à rede).
- [ ] crt.sh costuma ser lento e instável: se der `FALHA` com 502 ou 503, rode de novo antes de concluir algo.
- [ ] XposedOrNot: veja se a linha diz "N vazamento(s)" (o formato 200 foi lido) ou "sem vazamentos (404); o formato da resposta 200 não foi visto". No segundo caso, confira à mão com um email seu que você sabe que vazou (`python -c "import osint; print(osint.lookup_email('seu@email.com')['lists'])"`) que a lista de vazamentos vem preenchida.
- [ ] Perfis: cada um dos 18 sites dá `ok` ("existe e um nome inventado não"). Para os que falharem com "o perfil de teste X não foi achado", abra o perfil no navegador: se a conta existe, a leitura do site mudou; se não, troque o usuário em `KNOWN_USERS` do `fontes.py`. As contas de Codeberg (Gusted), Duolingo (duolingo), Keybase (chris), Mastodon (Gargron), Bluesky (jay) e Scratch (griffpatch) foram escolhidas sem poder abrir os sites.
- [ ] PyPI: dá `FALHA` se o site ainda responder com a página "Client Challenge"; nesse caso o Jarvis já mostra o PyPI em "Não deu para saber" na busca de usuário. Decida se vale tirá-lo da lista `SITES` do `osint.py`.
- [ ] Cotações e Clima (AwesomeAPI e Open-Meteo): `ok`, com o dólar e o clima de São Paulo plausíveis.
- [ ] Internet: latência, download e upload dão `ok`, e o comando termina em poucos segundos (baixa 200 KB e envia 50 KB, bem menos que o "como está a minha internet?").
- [ ] Com o Wi-Fi desligado, todas as fontes dão `sem rede` (nenhuma `FALHA`), o comando termina com código 2 (`echo %ERRORLEVEL%`) e leva só alguns segundos a mais por causa da segunda tentativa.
- [ ] `python doctor.py --fontes --ignorar pypi,reddit` mostra os dois como `ignorada` e o código de saída não conta o estado deles.
- [ ] No GitHub, em Actions, o workflow "Fontes externas" aparece e, em "Run workflow", roda sem erro de instalação. Ele não aparece nos checks de um pull request. Anote quais fontes o GitHub não consegue alcançar ou que o bloqueiam (Reddit, PyPI e a API do GitHub são os suspeitos) e use `--ignorar` no `fontes.yml` para elas.

## Tarefas nos avisos proativos

Detalhes em [avisos.md](avisos.md#tarefas-do-dia) e [dia-a-dia.md](dia-a-dia.md#aviso-de-manhã). Os testes automáticos usam um relógio falso; aqui você confere com o relógio, a voz e a câmera de verdade. Com `JARVIS_PROACTIVE=true`, `JARVIS_ENABLE_DAY=true` e `python jarvis.py`.

- [ ] Prepare a lista: "tenho que fechar o relatório até ontem" (ou uma tarefa com prazo passado), "tenho que ir ao dentista hoje" e "anota aí: ideia do painel". Para não esperar a manhã seguinte, troque o valor de `tasks_notice_day` no `lembretes.json` por `null` (ou apague a linha), numa hora entre 5h e 12h. Pode ser com o Jarvis ligado: o monitor lê o arquivo a cada minuto. Repita isso sempre que o item pedir para "zerar o `tasks_notice_day`".
- [ ] Com o link aberto, em até 1 minuto o Jarvis fala algo como "1 tarefa atrasada e 1 para hoje: fechar o relatório; ir ao dentista", sem ler a nota. O HUD mostra o aviso "Tarefas" e ele entra no registro de atividades.
- [ ] Reinicie o `jarvis.py` no mesmo dia: o aviso não repete (o `lembretes.json` tem `tasks_notice_day` com a data de hoje).
- [ ] Com o link fechado (diga "tchau, Jarvis" e zere o `tasks_notice_day`), o aviso aparece só no HUD: nada de bipe, o navegador não abre sozinho.
- [ ] "Para de me avisar sobre tarefas", zere o `tasks_notice_day`: o aviso aparece só no HUD, sem voz. "Pode voltar a avisar sobre tarefas" desfaz.
- [ ] Horário de silêncio: ponha um que cubra a hora atual (por exemplo `JARVIS_QUIET_HOURS` ou "horário de silêncio das 8h às 20h", de acordo com a hora) e zere o `tasks_notice_day`: nada é dito. Ao desligar o silêncio ("desliga o horário de silêncio"), o aviso sai em até 1 minuto.
- [ ] Presença: com `JARVIS_PRESENCE=true` e a câmera ligada, saia da frente do PC até a presença marcar "ausente" e zere o `tasks_notice_day`: nada é dito. Volte para a frente da câmera: o aviso sai pouco depois.
- [ ] Sem tarefa atrasada nem para hoje (marque as duas como feitas), zere o `tasks_notice_day` e espere 1 minuto: nenhum aviso, e `tasks_notice_day` volta com a data de hoje.
- [ ] Depois do meio-dia (ou antes das 5h) o aviso não sai, mesmo com tarefas atrasadas.
- [ ] Com `JARVIS_ENABLE_DAY=false` no `.env`, o aviso das tarefas nunca aparece, mesmo com o `tasks_notice_day` zerado e tarefas atrasadas. Os outros avisos (bateria, lembretes) continuam.

## Foco integrado com presença, avisos e bandeja

Detalhes em [dia-a-dia.md](dia-a-dia.md#foco-foc-47), [avisos.md](avisos.md#durante-o-foco) e [bandeja.md](bandeja.md#avisos-do-jarvis-na-bandeja). Os testes automáticos usam relógio falso, presença falsa e um ícone falso; aqui você confere com o relógio, a câmera, a voz e o Windows de verdade. Use `JARVIS_PROACTIVE=true`, `JARVIS_PRESENCE=true`, `JARVIS_ENABLE_CAMERA=true` e `pythonw jarvis.py --tray`, e apague o `foco.json` antes de começar se sobrou uma sessão.

Servidor e HUD:

- [ ] "Começa um foco de 2 minutos com pausa de 1, três blocos". O painel Foco e o chip do topo mostram "Foco 1/3" quase na hora. Recarregue a página, depois feche a aba e abra de novo: a contagem está onde devia (não reiniciou).
- [ ] Reinicie o Jarvis pelo menu da bandeja no meio de um bloco: depois de subir, o HUD mostra a mesma sessão, com o tempo certo. O `foco.json` aparece na pasta do projeto e não vai para o `git status`.
- [ ] Feche o Jarvis por mais tempo que um bloco e suba de novo: a sessão está no bloco que o relógio manda e só a última troca é avisada.
- [ ] Pelo painel, "Pular bloco" e "Encerrar" funcionam; por voz, "quanto falta do foco?" fala o tempo e "encerra o foco" tira o chip do topo na hora (até uns 3 segundos).
- [ ] Abra o HUD em dois navegadores (ou no celular pareado): os dois mostram a mesma contagem, e "pula esse bloco" por voz muda os dois.

Troca de bloco sem aba (precisa do ícone da bandeja):

- [ ] Com o foco rodando e o link fechado, feche a aba do HUD. Na troca do bloco aparece uma notificação do Windows "Jarvis" com "Hora da pausa. Bloco 1 de 3 concluído...", em até uns 3 segundos, sem abrir o navegador nem o link. A notificação some sozinha e não repete.
- [ ] Com a aba aberta e o link fechado: som de timer, notificação do HUD e também a notificação do Windows. Com o link aberto: o Jarvis fala a troca, sem notificação do Windows.
- [ ] "Para de me avisar sobre o foco": na troca seguinte não há voz (só HUD e bandeja). "Pode voltar a avisar sobre o foco" desfaz.
- [ ] Sem o ícone da bandeja (sem `--tray`) e sem aba: nada aparece na hora; ao abrir a aba o registro de atividades já mostra o que aconteceu e o chip tem o bloco certo. Anote se isso é suficiente para você ou se prefere o aviso abrir o link.
- [ ] Horário de silêncio cobrindo a hora atual: a troca não fala, mas a notificação do Windows e o HUD continuam.

Presença:

- [ ] Com a câmera e a presença ligadas, comece um foco de 10 minutos e fique na frente do PC: nada muda.
- [ ] Saia da frente da câmera por menos de 1 minuto e volte: o foco não pausa.
- [ ] Saia por uns 2 minutos: o chip do topo e o anel passam a "parado" (uns 1 a 1,5 minuto depois de sair). Fique fora um tempo conhecido (por exemplo 3 minutos) e volte: a contagem retoma e o Jarvis avisa "Foco retomado... Faltam N min", com N batendo com o que faltava quando você saiu, menos uns 20 segundos (o tempo que a presença leva para notar a saída). A ausência inteira não foi descontada.
- [ ] "Quanto falta do foco?" durante a pausa fala "pausado porque você saiu".
- [ ] Durante a pausa (descanso) saia por mais de 1 minuto: nada pausa. Se o descanso acabar com você fora, o próximo bloco começa e para até você voltar.
- [ ] Desligue a presença ("desliga a presença") com o foco parado pela ausência: a contagem volta a andar, sem aviso.
- [ ] Com `JARVIS_PRESENCE=false` (ou a câmera desligada), sair da frente do PC não muda nada na contagem.
- [ ] A volta da presença ao mesmo tempo que o "bem-vindo de volta" do PRS-25 (ausência de mais de 2 minutos com o link fechado): o Jarvis não fala duas coisas atropeladas. Anote como ficou.

Avisos esperam o bloco:

- [ ] Durante um bloco de foco, baixe um arquivo pelo navegador (aviso de download) e marque um lembrete para daqui a 1 minuto. Nada aparece nem fala durante o bloco. Quando a pausa começa, o Jarvis fala a troca e, em seguida, o download e o lembrete, cada um com "(chegou às HH:MM, durante o foco)".
- [ ] Um lembrete pedido como urgente ("me lembra daqui a 1 minuto de ligar pro contador, é urgente") fala na hora, no meio do bloco.
- [ ] Tire o carregador do notebook durante o bloco: nada. Com a bateria em 10% (ou simulada): o aviso crítico fala na hora.
- [ ] "Encerra o foco" com avisos esperando: eles saem em até uns 5 segundos.
- [ ] Com `JARVIS_ENABLE_DAY=false`, os avisos nunca esperam (e o painel Foco não responde).
