# Roteiro de testes em casa (Windows)

Checklist único dos recursos novos, de todos os branches já juntados na `main`. Os testes
automáticos (`python -m pytest` e, em `web/`, `npm test`) cobrem a lógica com simulações; o que
está aqui só dá para conferir na máquina real: webcam, microfone, os 3 monitores, o Google, o
Gemini de verdade e o celular. O passo a passo detalhado de cada item está na seção do README
indicada.

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

Confira no `doctor.py` as linhas "Link fecha sozinho: nunca" e a lista de modelos, todos "livre".
Não há dependência nova de Python; o `--rebuild` é obrigatório para o HUD novo e instala sozinho as fontes novas do HUD (o `npm install` roda quando o `package-lock.json` mudou).

Teste um grupo por vez. Se algo falhar, copie a linha do terminal com a tag do protocolo
(`[GST-18]`, `[MOU-20]`, `[DIT-29]`...) e, nos gestos, grave um trace com `--trace`.

## 1. Gestos: precisão e calibração (README → "Precisão e calibração")

- [ ] `python gestures.py --calibrate`: as 6 poses terminam com acerto ≥ 90%.
- [ ] `python gestures.py --preview --dry-run`: com a mão parada a confiança fica verde e a pose estável não pisca; punho frouxo continua `fist`.
- [ ] Segurando uma janela, tirar a mão do quadro pela lateral mostra "Cancelado" e não move nada.
- [ ] Gestos funcionam com a mão a ~30 cm e a ~1 m da câmera.
- [ ] Mouse no ar (`m` no preview): cursor parado não treme; movimento rápido chega ao outro monitor.

## 2. Gestos novos e personalizáveis (README → "Gestos personalizáveis")

- [ ] 👌 parado pausa/retoma a mídia.
- [ ] Pinça subindo/descendo muda o volume de 5 em 5%.
- [ ] 🤘 aplica o layout "modo trabalho" (salve antes: "salva esse layout como modo trabalho").
- [ ] Janela pega + 1, 2 ou 3 dedos parados → vai para a tela 1, 2 ou 3 do "Identificar".
- [ ] Tapar a webcam ~1 s muta/desmuta o Jarvis; apagar a luz sem a mão na frente não faz nada.
- [ ] Duas palmas se afastando estendem a janela; se aproximando, restauram.
- [ ] Por voz: "quando eu fizer joinha, pausa a música", "o que faz o rock?", "lista meus gestos"; "o rock fecha a janela" é recusado.

## 3. Painel de gestos com câmera e mapa das telas (README → "Painel de gestos")

- [ ] "Mostra o painel de gestos" (ou ✌ parado ~1 s): o painel aparece no canto inferior direito do notebook, com a câmera e o mapa dos 3 monitores.
- [ ] Arraste uma janela do notebook para o monitor de cima pelo mapa (punho em cima dela, mover, abrir a mão).
- [ ] Repita para o monitor vertical (à esquerda, x negativo).
- [ ] O painel não aparece nos prints do Jarvis ("o que tem na tela?").

## 4. Palavra de ativação e voz (README → WAK-22 e VOZ-30)

- [ ] `python wake_word.py --test`: "Jarvis" passa do limiar; frases comuns não.
- [ ] Diga "Jarvis": bipe, o link abre e ele responde no tom do mordomo britânico.
- [ ] "Quais vozes você tem?" e "troca sua voz para Orus"; "volta pra sua voz normal".
- [ ] Sons do HUD (link, ferramenta, confirmação, erro, timer) e o volume no painel Sistema.

## 5. Mouse, teclado e ditado (README → MOU-20 e DIT-29)

- [ ] "Abre o bloco de notas e digita olá"; ESC ou mexer no mouse cancela.
- [ ] No Bloco de Notas: "modo ditado", dite com "vírgula", "ponto de interrogação", "nova linha", "apaga a última palavra", "desfaz", depois "fim do ditado".
- [ ] No WhatsApp Web, "nova linha" não envia a mensagem.
- [ ] "Escreve aqui: chego em 10 minutos" fora do modo ditado.

## 6. Presença pela câmera (README → "Presença (PRS-25)")

> Aviso: os gestos ainda abrem a webcam por conta própria. Com presença e gestos ligados ao
> mesmo tempo, o Windows pode recusar a segunda abertura ("câmera em uso"). Teste a presença
> com os gestos desligados, e depois os dois juntos para ver se a sua webcam aguenta.
>
> Com `JARVIS_WAKE_SILENCE_SECONDS=0`, o link que a presença abre também só fecha com
> "tchau, Jarvis" ou o botão.

- [ ] (Opcional) com o Jarvis fechado: `python presence.py --enroll` e `python presence.py --test`.
- [ ] Saia da frente do PC por mais de 5 min: a mídia pausa (e o PC bloqueia, se `JARVIS_PRESENCE_LOCK=true`).
- [ ] Volte: "Bem-vindo de volta, senhor" com o resumo do tempo fora.
- [ ] Painel Sistema mostra "Presente" / "Ausente há X min".

## 7. Rotinas (README → "Rotinas (ROT-24)")

- [ ] "Bom dia, Jarvis": clima, manchetes, lembretes, layout de trabalho e playlist, com cada passo no painel Rotina.
- [ ] "Modo foco": pomodoro e volume baixo. "Boa noite" pede confirmação antes de bloquear o PC.
- [ ] "Cria uma rotina estudo que abre o Notion e põe lo-fi" e depois "roda a rotina estudo".
- [ ] "Todo dia útil às 8h roda o bom dia" (teste com um horário daqui a 2 min).

## 8. Google Agenda (README → "Google Agenda (AGD-27)")

- [ ] Crie as credenciais OAuth (passo a passo no README) e rode `python calendar_tools.py --login` e `--hoje`.
- [ ] "O que eu tenho hoje?", "e amanhã?", "qual minha próxima reunião?".
- [ ] "Marca dentista sexta às 15h": só grava com "confirmar agenda" + código.
- [ ] Evento daqui a 12 min: uns 10 min antes o Jarvis abre o link sozinho e avisa.

## 9. Avisos proativos e lembretes (README → "Avisos proativos e lembretes (PRO-28)")

- [ ] "Me lembra daqui a 2 minutos de beber água": com o link fechado ele abre e avisa.
- [ ] Tire o carregador; termine um download na pasta Downloads.
- [ ] "Para de me avisar sobre bateria" e "horário de silêncio das 22h às 6h".

## 10. Explicar a tela (README → "Assistente de tela (TEL-31)")

- [ ] No PowerShell, um erro de Python + "explica esse erro": causa e correção no painel.
- [ ] "O que tem de errado aqui?" com o mouse sobre o erro, inclusive no monitor vertical.
- [ ] "Copia a correção" e Ctrl+V: vem o bloco certo, e o Jarvis nunca digita sozinho.
- [ ] Com o `.env` aberto, o painel avisa que ocultou segredos.

## 11. Celular na rede de casa (README → "Celular na rede de casa (LAN-26)")

- [ ] `python jarvis.py --lan`: o HUD do PC mostra o QR de pareamento.
- [ ] No celular, aceite o certificado (passo a passo do Android/iPhone no README), pareie e fale com o Jarvis.
- [ ] Peça algo no PC pelo celular ("abre o YouTube no monitor de cima").
- [ ] Revogue o aparelho no HUD: o celular perde o acesso na hora, inclusive ao feed da câmera.

## 12. Link, modelos e tempo de resposta (README → "Modelos, cota e tempo de resposta")

- [ ] Abra o link e fique 20 min sem falar: ele continua aberto e responde na hora quando você volta (a sessão passa dos 15 min graças à compressão de contexto).
- [ ] Converse alguns turnos: o painel Sistema mostra "Tempo de resposta" (verde até 1,5 s) com a média, e o terminal do agente registra "Resposta em X s (modelo)".
- [ ] Troca de modelo: ponha `GOOGLE_MODEL=gemini-teste-live` (não existe), abra o link: ele conversa pelo próximo modelo, a notificação "Modelo de reserva" aparece e o painel mostra "Modelo · reserva". `python doctor.py` lista o modelo falso "em pausa". Depois volte o `GOOGLE_MODEL` de antes.
- [ ] Depois de uma troca de modelo, "troca sua voz para Orus" continua valendo na hora.
- [ ] `JARVIS_MODEL_ROTATION=rotate`: abra e feche o link 3 vezes; o painel Sistema mostra um modelo diferente a cada link.
- [ ] (Opcional) `JARVIS_END_OF_SPEECH_MS=500` e compare o tempo de resposta; se ele cortar a sua frase, suba para 900.

## 13. Visual do HUD (README → "Visual do HUD")

- [ ] Boot: o anel do reator se completa, aparece "Todos os sistemas online" e os painéis entram em cascata.
- [ ] Ao processar, o HUD inteiro fica âmbar deslizando (sem piscar); numa falha, vermelho. Numa conversa de vários turnos, o núcleo e o HUD não piscam entre "processando" e "respondendo" nem nas pausas entre frases.
- [ ] "Como está o tempo em Lisboa?": a placa sobre o núcleo mostra `WX-01 · Varredura meteorológica · Lisboa` e depois "✓ Concluído"; o painel tem o gráfico das próximas 24 h (passe o mouse).
- [ ] A legenda da fala do Jarvis aparece palavra por palavra embaixo do núcleo e some alguns segundos depois (desliga em Ajustes).
- [ ] Ajustes → Protocolo: os quatro mudam nome, marca, núcleo 3D, painéis, fontes e sons (veja o item 14).
- [ ] Modo cinema: tecla `F`, o botão ao lado do dock e "modo cinema" por voz; `Esc` ou "mostra os painéis de novo" voltam.
- [ ] "Pesquise sobre fusão nuclear": o globo cresce, os anéis recuam e cada destino ganha cidade e site.
- [ ] "Rode um diagnóstico": aparece "Ao vivo" e CPU/RAM se mexem (abra um app pesado para ver subir).
- [ ] "O que eu tenho hoje?" (com a agenda ligada): o dia em blocos, com o marcador de agora; passe o mouse nos blocos.
- [ ] Notificações à direita: um timer de 1 min acabando, um lembrete do item 9 e um download concluído.
- [ ] Arraste o painel Registro pelo cabeçalho para a coluna da esquerda; F5 e ele continua lá; "Restaurar painéis" em Ajustes desfaz.
- [ ] Modo ambiente: feche o link e não mexa em nada por 3 min: relógio grande, clima da `JARVIS_HOME_CITY` e a próxima reunião. Mexer o mouse ou dizer "Jarvis" volta ao HUD.
- [ ] Ajustes → Qualidade: mostra o nível e os fps. Em "Automática" num PC mais fraco, ela desce sozinha depois de ~8 s lenta, uma vez, e o Registro diz "Qualidade da cena: Média (32 fps)".
- [ ] Ajustes → Som do reator: com o link aberto, o zumbido cresce quando o Jarvis fala.
- [ ] No celular pareado (item 11): tema, legenda e modo cinema funcionam; os painéis não se arrastam no celular, de propósito.

## 14. Protocolos (README → "Protocolos do HUD")

- [ ] Ajustes → Protocolo → F.R.I.D.A.Y. com o link fechado: boot, marca e nome na barra mudam; abra o link: ela cumprimenta ("Boa noite, chefe. F.R.I.D.A.Y. na escuta...") com voz feminina (Kore) e a transcrição mostra "F.R.I.D.A.Y.".
- [ ] Com o link aberto, "Jarvis, modo Mark III": ele confirma na voz atual, a conversa fica quieta um instante e o Mark III se apresenta em outra voz (Orus); a holografia se rematerializa com o reator arc e a mira. Pergunte o clima: resposta curta, de relatório.
- [ ] Clique em Stealth no meio da conversa: sem partículas e sem brilho, sons baixinhos, voz sussurrada e respostas de uma frase.
- [ ] "Troca sua voz para Aoede" com a F.R.I.D.A.Y.; volte ao J.A.R.V.I.S. (continua a voz dele) e de novo à F.R.I.D.A.Y. (Aoede).
- [ ] Abra o HUD no celular pareado: ele mostra o mesmo protocolo do PC.
- [ ] `persona.json` aparece ao lado do projeto e não entra no `git status`.

## 15. Painel Gestos (README → "Painel Gestos no HUD")

- [ ] Com `JARVIS_ENABLE_GESTURES=true`, o painel Gestos aparece na coluna da direita; sem link os botões ficam apagados e o editor funciona.
- [ ] Abra o link e clique em Ligar: "Abrindo a câmera…" e depois "Armados". Mão aberta, punho, mova e abra: o painel mostra "✊ Chrome → monitor de cima" e depois o resultado.
- [ ] Mouse no ar e Painel da câmera pelos botões ligam e desligam; o estado acompanha também quando você usa os gestos (✌ parado abre o painel).
- [ ] Editar → rock → Abrir app → spotify → Salvar; faça 🤘: o Spotify abre sem reiniciar nada.
- [ ] Editar → OK → Atalho → `alt+f4` → Salvar: é recusado com a explicação; nada muda no `gestos.json`.
- [ ] Ligue o joinha a "tocar/pausar": o painel avisa que ele faz o mesmo que o OK. "Restaurar todos" volta tudo ao padrão.
