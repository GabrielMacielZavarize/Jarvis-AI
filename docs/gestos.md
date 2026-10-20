# Gestos das mãos

Protocolo GST-18. Você controla as janelas com a mão na frente da webcam, usando o MediaPipe Hands, tudo rodando local.

Ligue com `JARVIS_ENABLE_GESTURES=true` e diga "liga os gestos", ou suba já ligado com `python jarvis.py --gestures`. Um aviso pequeno no topo do monitor para onde você está olhando mostra o estado. Ele fica sempre por cima, não rouba o foco e não captura cliques.

## Gestos fixos

| Gesto | O que faz |
| --- | --- |
| Mão aberta parada por 1 s | Arma os gestos. Desarmado, nada acontece. Desarma sozinho depois de uns 12 s sem uso ou 5 s sem a mão no quadro |
| Fechar a mão | Pega a janela em foco |
| Mão fechada, mover para um lado e abrir | Joga a janela para o monitor que fica fisicamente daquele lado: cima vai para o monitor de cima, baixo para o notebook, esquerda para o vertical. Do vertical, baixo vai para o notebook e direita para o monitor na altura da janela. O aviso mostra o destino antes de soltar, e abrir a mão já solta, mesmo com o polegar encostado |
| Fechar e abrir a mão sem mover | Maximiza. Se já estava maximizada, restaura |
| Palma descendo rápido e parando dentro do quadro | Minimiza a janela em foco. Baixar a mão até sair do quadro não conta |
| Palma de um lado para o outro, 3 traços em até 2 s ("apagar o quadro") | Desfaz o último movimento. A janela volta para onde estava, com a mesma memória do "volta pra onde estava" da voz |
| Polegar para baixo segurado por 1,2 s (a mão pode ficar meio fechada) | Fecha a janela em foco, com contagem visível. Soltar antes cancela. No navegador fecha só a aba ativa, nunca a do HUD |
| Dois dedos indo para a direita ou para a esquerda | Próxima ou anterior aba, só com o navegador em foco. O movimento de volta é ignorado |
| Dois dedos parados por 1 s | Abre e fecha o painel de gestos. Por voz: "mostra o painel de gestos", "esconde o painel de gestos" |
| Indicador parado por 1 s | Liga o mouse no ar: a mão move o cursor por todos os monitores, inclusive o vertical. Pinça ou fechar a mão rápido clica, segurar arrasta e a palma aberta parada por 1 s sai. Por voz: "liga o mouse no ar", "desliga o mouse no ar" |
| Com uma janela pega, 1, 2 ou 3 dedos parados por meio segundo | Manda a janela para a tela 1, 2 ou 3 (os números do Identificar do Windows). O aviso mostra "TELA 2" enquanto conta |

## Apontar e falar

Com os gestos armados, aponte com o indicador para um lugar de qualquer monitor e diga "Jarvis, explica isso aqui". O "aqui" passa a ser o ponto para onde a mão aponta, não o cursor do mouse, que fica onde estava. Funciona com o "o que tem de errado aqui?" e os outros pedidos do [assistente de tela](assistente-de-tela.md#apontando-com-o-dedo).

Enquanto o indicador está esticado, uma mira pequena aparece no ponto, e some cerca de 1 s depois de você baixar a mão. Ela não captura cliques e não aparece nos prints. O ponto usa o mesmo mapeamento do mouse no ar: a mão funciona como um trackpad no ar, não como um raio saindo do dedo. Por isso a mira serve para acertar o lugar antes de falar.

Apontar sozinho nunca clica nem move o cursor. Com o mouse e teclado ligados, "Jarvis, clica aqui" ou "digita olá aqui" agem no ponto apontado (veja [mouse-e-ditado.md](mouse-e-ditado.md#clica-aqui-apontando)). Antes do clique a mira fica parada no ponto, mesmo com a mão já baixada, e o aviso mostra "CLICANDO AQUI". O ponto vale por 2,5 s depois da última vez que o dedo ficou parado, então dá tempo de terminar a frase com a mão já baixada.

O indicador parado também liga o mouse no ar, e a regra para os dois não brigarem é a fala: se você começa a falar enquanto aponta (ou até 2 s depois de uma fala), o indicador vira só o ponteiro e o aviso mostra "APONTANDO". Esse mesmo indicador não liga o mouse no ar até você baixar a mão ou mudar de pose. Sem falar, o indicador parado por 1 s liga o mouse no ar como sempre. Se o mouse no ar já tiver ligado, o cursor está onde o dedo aponta e o "aqui" também funciona.

A fala é percebida pela própria sessão de voz, então isso só vale com o link aberto. Precisa também do controle do PC (`JARVIS_ENABLE_PC_CONTROL=true`), que é onde fica o assistente de tela.

## Gestos personalizáveis

Estes disparam uma ação que você escolhe, guardada no `gestos.json` (ignorado pelo git, só guarda o que você mudou). Os que exigem segurar mostram no aviso o nome da ação com uma contagem antes de executar, e soltar antes cancela. Os rápidos (pinça, duas mãos) mostram o nome da ação enquanto ela roda.

| Gesto | Nome no arquivo | Padrão |
| --- | --- | --- |
| OK parado por 0,8 s (polegar no indicador, os outros três dedos esticados) | `ok` | Tocar ou pausar a mídia |
| Pinça subindo ou descendo | `pinca_sobe`, `pinca_desce` | Volume 5% para cima ou para baixo a cada degrau (mais ou menos um terço de palma de movimento) |
| Rock parado por 0,7 s (indicador e mindinho) | `rock` | Aplicar o layout "trabalho" (salve antes com "salva esse layout como modo trabalho") |
| Joinha parado por 0,7 s | `joinha` | Nada, fica livre para você usar |
| Palma tapando a câmera por 1 s | `tapar_camera` | Muta e desmuta o microfone do Jarvis na conversa. Funciona mesmo desarmado. Tape de novo para ele voltar a ouvir, já que mudo ele não escuta "desmuta" |
| Duas palmas abertas se afastando ou se aproximando | `maos_afastam`, `maos_aproximam` | Maximizar ou restaurar a janela em foco |

Não existe o gesto de silêncio com o indicador nos lábios: o detector só vê mãos, não o rosto, e um indicador parado já liga o mouse no ar (ou aponta, se você estiver falando). Tapar a câmera faz esse papel sem confusão.

Dá para mudar por voz ("lista meus gestos", "o que faz o rock?", "quando eu fizer joinha, pausa a música", "o rock abre o Spotify", "o OK aperta ctrl+shift+m", "volta o rock ao padrão") ou editando o arquivo:

```json
{
  "joinha": {"tipo": "acao", "acao": "play_pause"},
  "rock": {"tipo": "app", "nome": "spotify"},
  "ok": {"tipo": "atalho", "teclas": "ctrl+shift+m"},
  "maos_afastam": {"tipo": "site", "url": "youtube.com"},
  "tapar_camera": {"tipo": "nada"}
}
```

Os tipos são `acao`, `layout`, `app`, `site`, `atalho` e `nada`. As ações aceitas em `acao` são `play_pause`, `next`, `previous`, `volume_up`, `volume_down`, `mute`, `unmute`, `mic_toggle`, `maximize`, `restore`, `minimize`, `undo`, `show_desktop`, `next_tab` e `previous_tab`.

Fechar, apagar e digitar nunca ficam num gesto. Atalhos como Alt+F4, Ctrl+W e Shift+Delete, teclas soltas (que digitariam) e instaladores são recusados, por voz e no arquivo. Para fechar continua o polegar para baixo, que pede confirmação segurando.

## Gestos no HUD

Com `JARVIS_ENABLE_GESTURES=true`, o HUD ganha o painel Gestos (GST-18), na coluna da direita. Ele mostra:

- O estado ao vivo: desligados, desarmados, armados, segurando uma janela (e o monitor para onde ela vai), contando para fechar ou no mouse no ar, e se o painel de gestos do canto está aberto.
- O último comando feito com a mão e se deu certo ("Tocar/pausar a mídia, há 4 s"). Cada comando também aparece na placa sobre o núcleo e no registro.
- Os botões Ligar e Desligar, Armar, Mouse no ar e Painel da câmera. Eles rodam no agente, que é quem tem a webcam, então precisam do link aberto. Quando o link abre, o painel pergunta o estado atual.
- O botão Editar, com os oito gestos personalizáveis e o que cada um faz agora (os que você mudou ficam destacados). Trocar abre o editor: ação, layout salvo, app, site, atalho ou nada. "Voltar ao padrão" e "Restaurar todos" desfazem. O painel avisa quando dois gestos fazem a mesma coisa e lista os gestos fixos.

O editor grava o mesmo `gestos.json` da voz, pela API `/api/gestures`, com as mesmas travas: Alt+F4, Ctrl+W, Shift+Delete e teclas soltas são recusados com a explicação. O motor relê o arquivo pela data de modificação, então a troca já vale no próximo gesto, sem reiniciar nada.

## Testando sem o agente

```bash
python gestures.py --preview             # webcam com os pontos da mão, a pose e o estado
python gestures.py --preview --dry-run   # reconhece tudo, mas não mexe em nenhuma janela
python gestures.py --calibrate           # mede a sua mão em cada pose
```

No preview, `q` sai, `a` arma, `d` desarma, `m` liga e desliga o mouse no ar e `p` abre e fecha o painel de gestos (`--panel` já abre com ele). Se abrir a webcam errada, use `JARVIS_CAMERA_INDEX=1`. Na primeira execução o modelo de mãos do MediaPipe (uns 8 MB) é baixado para `.cache/models/` e conferido por SHA-256.

## Painel de gestos

"Mostra o painel de gestos", ou dois dedos parados por 1 s com os gestos armados, abre um painel pequeno no canto (por padrão, inferior direito do notebook, 360 por 260, escalado pelo DPI daquele monitor). Ele mostra três coisas:

1. A webcam com os pontos da mão e o estado do gesto (o mesmo texto do aviso do topo), com os quadros por segundo.
2. O mapa dos monitores na disposição real do Windows, com as mesmas coordenadas das Configurações: o de cima, o notebook embaixo e o vertical à esquerda (x negativo). Os monitores vêm numerados como no Identificar, com as janelas abertas dentro de cada um e miniaturas delas.
3. Um cursor da mão sobre o mapa.

Para mover uma janela pelo mapa, ponha a mão sobre ela (fica com borda azul), feche a mão para pegar, leve até outro monitor (ele fica verde e o aviso diz "monitor de cima") e abra a mão para soltar. A janela vai para aquele monitor na mesma posição e tamanho relativos que tinha no de origem: metade esquerda continua metade esquerda, inclusive entre monitores com DPI diferente, e maximizada continua maximizada. Soltar no mesmo monitor não muda nada, e o "apagar o quadro" desfaz como sempre.

Como o mapa convive com o resto:

- Ele só funciona com o painel aberto e os gestos armados. O cursor da mão percorre o mapa inteiro com a mesma região da câmera do mouse no ar (o centro do quadro), então não precisa esticar o braço.
- Fechar a mão fora de qualquer janela do mapa continua pegando a janela em foco, com o arremesso por direção de sempre. Os outros gestos (minimizar, desfazer, abas, fechar) não mudam.
- O mouse no ar tem prioridade. Com ele ligado, o mapa só mostra onde o cursor real está (seta amarela) e o punho ou a pinça clicam como sempre. Ao sair do mouse no ar, o cursor da mão volta ao mapa.
- O painel não captura cliques do mouse de verdade. Quem mexe nele é a mão.
- Esconder o painel no meio de um arrasto cancela o arrasto, e desligar os gestos fecha o painel.

Sobre desempenho: o motor dos gestos só passa ao painel uma cópia pequena do quadro (uns 220 pixels), e o desenho roda em outra thread, no máximo 15 vezes por segundo e só quando algo muda. Assim o loop dos gestos não perde quadros. A lista de janelas é relida a cada segundo, e as miniaturas (PrintWindow) são tiradas uma por vez, cada janela no máximo a cada 1,5 s, numa thread de prioridade baixa. Apps que o PrintWindow não consegue desenhar (alguns jogos e vídeos com GPU) aparecem como um retângulo colorido com a inicial.

Quadros e miniaturas ficam só na memória. Nada é gravado nem enviado, e o painel, como o aviso, fica fora dos prints do `look_at_screen`.

| Variável | Padrão | O que faz |
| --- | --- | --- |
| `JARVIS_GESTURE_PANEL_CORNER` | `inferior-direito` | Canto: `inferior-direito`, `inferior-esquerdo`, `superior-direito` ou `superior-esquerdo` |
| `JARVIS_GESTURE_PANEL_MONITOR` | `notebook` | Monitor do painel: número ou nome da tela ("2", "de cima", um apelido). Se esse monitor não existir, vai para o notebook ou para a tela principal |
| `JARVIS_GESTURE_PANEL_OPACITY` | `0.92` | Opacidade, de 0.3 a 1 |
| `JARVIS_GESTURE_PANEL_SIZE` | `360x260` | Tamanho em pixels lógicos, multiplicado pela escala do monitor |

## Precisão e calibração

Os 21 pontos da mão passam por um filtro One Euro antes de virar pose, e o centro da mão e o mouse no ar têm o seu próprio. Parado, o filtro segura a tremedeira. Num movimento rápido ele abre na hora, então arremessos e swipes não ficam para trás.

Uma pose nova só vale depois de 4 quadros seguidos, e a atual é solta com 3. Um quadro errado no meio, com o detector em dúvida, não muda nada.

Quadros ruins são descartados: confiança baixa do MediaPipe, mão saindo pela borda ou palma que "pula" de tamanho de um quadro para o outro valem como "sem mão". Por isso, levar a mão para fora do quadro segurando uma janela cancela em vez de jogá-la.

As distâncias usam o tamanho da palma, então o swipe de abas, o "apagar o quadro" e a "mão parada" se ajustam a quão perto você está da câmera.

### Calibração guiada

`python gestures.py --calibrate` abre a webcam e pede, uma de cada vez, mão aberta, punho, pinça, indicador, dois dedos e polegar para baixo (contagem de 2,5 s, depois 2 s medindo). Ele mede as curvas dos dedos, o alcance, o polegar e a pinça da sua mão, coloca cada limiar no meio do vão entre as poses e grava em `gestos_calibracao.json` (fora do git). Se os limiares medidos acertarem menos que os padrão, nada muda. No fim mostra o acerto de cada pose antes e depois.

Daí em diante os gestos e o preview usam o arquivo. Para voltar ao padrão, apague-o. Faça a calibração na distância e na luz em que você usa.

O preview mostra, além do estado, a confiança do detector, quanto da mão está no quadro, a pose do quadro e a pose estável, avisa quando um quadro foi descartado (e por quê) e diz se a calibração é a sua ou a padrão. A barra da direita é a confiança, em verde, amarelo ou vermelho.

### Traces de regressão

`python gestures.py --preview --dry-run --trace meu_gesto.jsonl` grava só números (pontos, confiança, pose, comandos), nunca imagens. Para virar teste, coloque o arquivo em `tests/traces/` com uma primeira linha listando os comandos esperados, por exemplo `{"expect": ["armed", "grab", "aim", "throw"]}`. O teste reproduz o trace no `GestureMachine` e confere. Já existem traces sintéticos dos casos difíceis: punho frouxo que não pode virar pinça, mão saindo do quadro e tremor.

## Como testar

Precisa de Windows com webcam. Os três roteiros abaixo valem primeiro com `--preview --dry-run` e depois de verdade.

### Precisão

1. `python gestures.py --calibrate`: faça as 6 poses e confira que todas terminam com acerto alto, 90% ou mais.
2. `python gestures.py --preview --dry-run`: com a mão parada a confiança fica verde e a pose estável não pisca. Feche a mão devagar e confira que o punho frouxo continua `fist` (e não `pinch`).
3. Arme, segure uma janela com o punho e leve a mão para fora do quadro pela lateral. Deve aparecer "Cancelado", sem mover nada.
4. Repita os gestos com a mão a uns 30 cm e a 1 m da câmera. Abas com dois dedos e "apagar o quadro" devem funcionar nas duas distâncias.
5. Mouse no ar (`m` no preview, sem `--dry-run`): com o indicador parado o cursor não treme, e um movimento rápido chega ao outro monitor sem ficar para trás.
6. Se algo falhar, grave com `--trace` e coloque o arquivo em `tests/traces/` para virar teste.

### Gestos personalizáveis

1. Arme e faça o OK parado: o aviso mostra "TOCAR/PAUSAR A MÍDIA" com contagem. Com um vídeo tocando, ele pausa e volta no segundo OK.
2. Pinça (com os outros dedos meio dobrados) subindo e descendo devagar: o volume muda de 5 em 5%. Um OK parado nunca deve mexer no volume.
3. Salve um layout ("salva esse layout como modo trabalho"), bagunce as janelas e faça o rock parado: as janelas voltam.
4. Pegue uma janela com o punho e mostre 1, 2 e 3 dedos parados: ela vai para a tela com aquele número. Confira que abrir a mão ainda maximiza e que mover e abrir ainda joga para o lado.
5. Com a conversa de voz ligada, tape a webcam com a palma por 1 s: o Jarvis para de ouvir. Tape de novo e ele volta. Apague a luz do quarto sem a mão na frente: nada deve acontecer.
6. Duas palmas abertas se afastando maximizam a janela em foco. Se aproximando, restauram.
7. Por voz: "quando eu fizer joinha, pausa a música", "o que faz o rock?", "lista meus gestos" e "o rock fecha a janela" (deve recusar). Confira o `gestos.json` criado na pasta do projeto.

### Gestos no HUD

1. Com o link fechado, abra o painel Gestos: os botões ficam apagados e o Editar funciona.
2. Abra o link e clique em Ligar: aparece "Abrindo a câmera…" e depois "Armados". Pegue uma janela com o punho e mova: o painel mostra a janela e o monitor de destino, e depois o resultado.
3. Mouse no ar e Painel da câmera pelos botões ligam e desligam. O estado acompanha também quando você usa os próprios gestos.
4. Editar, rock, Abrir app, `spotify`, Salvar. Faça o rock: o Spotify abre sem reiniciar nada.
5. Editar, OK, Atalho, `alt+f4`, Salvar: é recusado com a explicação e o `gestos.json` não muda.
6. Ligue o joinha a "tocar/pausar": o painel avisa que ele faz o mesmo que o OK. "Restaurar todos" volta tudo ao padrão.

### Painel de gestos

1. `python gestures.py --preview --dry-run --panel`: o painel aparece no canto inferior direito do notebook, com a câmera e a mão desenhada. O mapa deve ter o vertical à esquerda, o de cima e o notebook embaixo, com os números do Identificar.
2. Abra 3 ou 4 janelas em monitores diferentes. Elas aparecem no lugar certo do mapa em até 1 s, com miniaturas em até 2 s. Mova uma janela com o mouse e veja o mapa acompanhar.
3. Arme, passe a mão sobre uma janela do mapa (borda azul), feche a mão, leve até o monitor de cima (fica verde) e abra a mão. No terminal sai "(simulação) ... na mesma posição relativa". Repita para o vertical.
4. Sem `--dry-run`: arraste uma janela que ocupa a metade esquerda do notebook para o monitor de cima e confira que ela ocupa a metade esquerda dele. Depois "apague o quadro" para desfazer. Teste também uma janela maximizada e uma do vertical para o notebook (DPIs diferentes).
5. Indicador parado para o mouse no ar: o mapa mostra a seta amarela seguindo o cursor real e o punho clica sem pegar janelas do mapa. Palma parada sai.
6. Dois dedos parados por 1 s fecham o painel e "Jarvis, mostra o painel de gestos" abre de novo. Com o painel aberto, o preview deve continuar perto de 30 fps.

### Apontar e falar

Com `JARVIS_ENABLE_PC_CONTROL=true`, os gestos armados e o link aberto:

1. Deixe um erro aberto no monitor vertical e o mouse parado no notebook. Aponte para o erro: a mira aparece onde a mão aponta. Ajuste até ela ficar em cima da mensagem.
2. Ainda apontando, diga "Jarvis, explica isso aqui". O aviso mostra "APONTANDO", o mouse não sai do lugar e o painel do assistente de tela diz "texto onde você apontou" (ou "print de onde você apontou"), com a explicação do erro certo.
3. Baixe a mão: a mira some em cerca de 1 s.
4. Sem apontar, "o que tem de errado aqui?" volta a usar o cursor do mouse.
5. Calado, indicador parado por 1 s: o mouse no ar liga como antes.
6. No `python gestures.py --preview`, aponte e fale perto do microfone algumas vezes. Se o mouse no ar ainda ligar antes de você começar a falar, anote quanto tempo você costuma levar entre apontar e falar.

### Clica aqui apontando

Com `JARVIS_ENABLE_COMPUTER_USE=true`, os gestos armados e o link aberto, siga a [seção 25 do roteiro](ROTEIRO_DE_TESTES.md#25-clica-aqui-apontando).
