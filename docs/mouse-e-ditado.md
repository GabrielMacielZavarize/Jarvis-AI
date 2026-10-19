# Mouse, teclado e modo ditado

## Mouse e teclado

Protocolo MOU-20.

```env
JARVIS_ENABLE_COMPUTER_USE=true
JARVIS_COMPUTER_USE_MODEL=gemini-3.8-flash
```

Com isso o Jarvis clica, digita, rola e usa atalhos por você: "clica no botão de play", "digita olá no bloco de notas", "rola a página", "abre o menu de configurações do Discord".

Precisa da `GOOGLE_API_KEY` mesmo se a voz for outro backend. Para achar o elemento descrito, um print do monitor vai para o `gemini-3.8-flash` pela API normal (não a Live), que devolve a caixa `box_2d` normalizada de 0 a 1000. Esse modelo está no plano gratuito, é o que o Google usa na documentação de detecção e o recomendado para computer use.

### Como ele clica

A caixa vira coordenada física da área de trabalho. Cada monitor tem o seu deslocamento (o vertical à esquerda tem `x` negativo) e o DPI de cada tela é respeitado (`win_desktop.physical_pixels`). O clique sai por `SendInput` e `SetCursorPos` via ctypes, e não pelo pyautogui, que se perde com vários monitores e coordenadas negativas.

Achar o elemento leva alguns segundos (de 4 a 8 nos meus testes, dependendo da carga do plano gratuito). A precisão medida foi de 1 a 2 pixels, inclusive no monitor vertical. Enquanto isso, o HUD mostra a ação em andamento.

O cursor desliza até o alvo e para um instante antes do clique, para você ver o que vai acontecer. Mexer no mouse ou apertar Esc no meio do caminho cancela.

### Como ele digita

A digitação sai tecla por tecla no layout do teclado ativo, respeitando Shift e Caps Lock. Acentos sem tecla própria vão como Unicode. Isso porque apps como o Bloco de Notas do Windows 11 embaralham texto enviado em rajada. Depois de digitar, o Jarvis confere o campo por UI Automation e avisa se o texto não chegou certo.

### Tarefas curtas

O `do_on_screen` repete o ciclo print, decidir, agir e conferir por no máximo 8 passos. Para quando o objetivo aparece na tela, quando você diz "Jarvis, para", aperta Esc ou mexe no mouse.

Cada ação abre o painel MOU-20 no HUD com o print, o alvo desenhado (caixa ciano e mira laranja) e o registro das últimas ações. O terminal registra a mesma linha com `[MOU-20]`.

As travas (senhas, janelas proibidas, atalhos liberados, confirmação de cliques arriscados) estão em [seguranca.md](seguranca.md#mouse-e-teclado).

## Modo ditado

Protocolo DIT-29. Vem junto com o mouse e teclado (`JARVIS_ENABLE_COMPUTER_USE=true`).

Clique no campo onde quer escrever (Bloco de Notas, WhatsApp Web, PhpStorm, Discord...) e diga "Jarvis, modo ditado". Um bipe duplo avisa que ligou e o indicador DITADO aparece no HUD com o texto saindo. A partir daí tudo que você fala é digitado ali, frase a frase, até "fim do ditado". Cada pausa de mais ou menos 1 segundo fecha uma frase, com um bipe curto. Enquanto isso o Jarvis não responde falando.

| Você fala | Vira |
| --- | --- |
| "vírgula", "ponto" ou "ponto final", "ponto de interrogação", "ponto de exclamação", "dois pontos", "ponto e vírgula", "reticências" | `,` `.` `?` `!` `:` `;` `...` |
| "nova linha" ou "pula linha", "novo parágrafo" | Um Enter ou dois (Shift+Enter em apps de conversa) |
| "apaga a última palavra", "apaga a última frase" | Backspace só sobre o que o ditado escreveu |
| "desfaz" | Desfaz a última frase ditada (de novo, a anterior) |
| "tudo maiúsculo" ... "fim do maiúsculo", "tudo minúsculo" | Caixa alta no trecho |
| "fim do ditado", "encerra o ditado", "para o ditado", "sai do ditado" | Desliga. Esc, mexer no mouse durante a digitação e 3 minutos de silêncio também desligam |

### Pontuação e maiúsculas

A pontuação que a transcrição do Gemini já coloca fica. Se você dita pontuação numa frase, só vale a falada, para não sair "Oi,,". Frase que termina sem pontuação ganha ponto, ou interrogação se começa com quem, como, onde, quando, qual, quanto, o que ou por que. Se depois da pausa você disser "vírgula", ela substitui esse ponto.

Cada frase começa com maiúscula. A maiúscula que a transcrição põe no começo de cada fala some quando ela cai no meio da frase, mas nomes como Gabriel, PhpStorm e WhatsApp ficam.

"Ponto" e "vírgula" usados como palavra continuam escritos: "no ponto", "ponto de ônibus", "uma vírgula".

### Uma frase só

"Escreve aqui: chego em 10 minutos" ou "digita aí que já vou" (`write_here`) escrevem as suas palavras, tiradas da transcrição da sua fala e não do que o modelo repetiu, com os mesmos comandos e sem ponto automático.

### Nada é enviado

No WhatsApp, Discord, Telegram, Teams e afins a nova linha sai como Shift+Enter. Apertar Enter para enviar fica com você.

Se você mudar de campo no meio, o ditado segue no campo novo e "apaga" e "desfaz" passam a valer só para o que foi escrito nele.

### Por que um hook nas transcrições

O texto digitado é exatamente o que você disse. O modelo não resume, não traduz, não "corrige", não precisa de uma ida e volta de ferramenta por frase e não depende de lembrar de chamar nada. Ele só liga o modo (`start_dictation`).

Depois disso o `dictation.py` escuta o evento `user_input_transcribed` do LiveKit, alimentado pela transcrição de entrada do Gemini Live (ligada por padrão; `JARVIS_TRANSCRIPTION_HINTS=true` ajuda com o vocabulário). A cada fala que o modelo começa (`speech_created`), ele interrompe a fala antes de tocar áudio ou rodar ferramenta. Como o Gemini só manda a transcrição final depois de terminar a própria resposta, o ditado usa as transcrições parciais assim que elas param de chegar (a pausa), e a final só completa o que faltou. O áudio continua indo para o Gemini durante o ditado: ele ouve tudo, mas fica calado.

### Limitações

Frases longas sem pausa só saem quando você pausa. "Apaga a última frase" dito como parte de um texto é entendido como comando. Os bipes precisam do HUD ou do alto-falante do PC (sem HUD conectado, sai um `winsound.Beep`).

### Como testar

1. `.env` com `JARVIS_ENABLE_COMPUTER_USE=true` (de preferência com `JARVIS_TRANSCRIPTION_HINTS=true`), `python jarvis.py` e o HUD conectado.
2. Abra o Bloco de Notas, clique dentro e diga "Jarvis, modo ditado". Espere o bipe duplo e o indicador DITADO. O Jarvis não deve falar nada.
3. Dite "oi vírgula tudo bem ponto de interrogação", pausa, "chego em 10 minutos", pausa, "nova linha tudo maiúsculo urgente", pausa, "fim do maiúsculo apaga a última palavra", pausa, "desfaz". No Bloco de Notas e no HUD deve aparecer `Oi, tudo bem? Chego em 10 minutos.` e depois `URGENTE`, que é apagado e volta. Um bipe curto por frase.
4. Diga "fim do ditado": bipe descendente e "Ditado encerrado". Fale algo e confira que nada mais é digitado e que o Jarvis volta a responder.
5. No WhatsApp Web, clique na caixa de mensagem, "modo ditado", "oi nova linha já chego", "fim do ditado". A mensagem não pode ter sido enviada: ficam duas linhas na caixa.
6. Travas: no meio de um ditado, mexa no mouse enquanto ele digita uma frase longa (para, com bipe grave). Ligue de novo e aperte Esc entre frases (desliga). Clique num campo de senha e dite algo (recusa no HUD, nada digitado). Dite "4111 1111 1111 1111" (recusado).
7. No PhpStorm e no Discord, um ditado curto em cada, conferindo acentos (ç, ã, é) e que o "nova linha" no Discord não envia.
8. Fora do ditado: "escreve aqui: chego em 10 minutos" no Bloco de Notas. Deve sair `Chego em 10 minutos` sem ponto, e o terminal registra `[DIT-29]`.
