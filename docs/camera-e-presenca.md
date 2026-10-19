# Câmera e presença

## Câmera

Protocolo CAM-19. O Jarvis olha pela webcam quando você pede, e o HUD mostra o feed ao vivo num painel com o aviso CÂMERA ATIVA sempre visível.

```env
JARVIS_ENABLE_CAMERA=true
# opcional: parte do nome ou índice da webcam; vazio = a primeira que não seja infravermelha
JARVIS_CAMERA=
```

A webcam pertence ao servidor do HUD (`camera.py`, iniciado pelo `python jarvis.py`). Ele é o único que a abre e reparte os quadros entre o feed do HUD, as fotos que o Jarvis analisa e os outros recursos. No Windows ela abre pelo Media Foundation (MSMF) em 1280x720 a 30 fps. Câmeras infravermelhas (Windows Hello) nunca são usadas.

O worker do agente é outro processo e pede a foto ao servidor por HTTP, no endereço que o `jarvis.py` passa em `JARVIS_HUD_URL` (padrão `http://127.0.0.1:8000`). Se o servidor não estiver de pé, o Jarvis diz isso em vez de inventar uma resposta.

Endpoints locais:

| Endpoint | O que faz |
| --- | --- |
| `GET /api/camera/state` | Estado da câmera |
| `GET /api/camera/snapshot` | Foto em JPEG |
| `GET /api/camera/stream` | Feed MJPEG |
| `POST /api/camera/on` | Mantém ligada |
| `POST /api/camera/off` | Desliga na hora, para tudo |

### Por que uma foto por pedido

Sessões de áudio e vídeo do Gemini Live duram uns 2 minutos sem compressão de contexto (contra 15 só com áudio), e cada quadro custa uns 258 tokens, o que esgota rápido o plano gratuito. Por isso o Jarvis manda uma foto por pedido, e o vídeo ao vivo fica só no seu HUD, sem sair do computador.

As regras de privacidade da câmera estão em [seguranca.md](seguranca.md#câmera).

## Presença

Protocolo PRS-25. O Jarvis percebe quando você sai e volta para a frente do PC.

```env
JARVIS_ENABLE_CAMERA=true
JARVIS_PRESENCE=true
JARVIS_PRESENCE_AWAY_MINUTES=5   # fora por mais que isso: pausa a mídia (e bloqueia, se ligado)
JARVIS_PRESENCE_LOCK=false       # true = bloqueia o PC quando você sai (muda por voz)
```

O `presence.py` roda dentro do servidor do HUD. Ele pede quadros ao mesmo hub da webcam que serve o feed e os gestos, e olha umas 2 vezes por segundo se há um rosto (MediaPipe Face Detector, uns 5 ms por quadro).

### Chegou

Rosto visto por 1,5 s seguidos (alguém passando não conta). Se você ficou pelo menos 2 minutos fora, o link abre pela mesma via da palavra de ativação (bipe no HUD e, sem aba aberta, o navegador abre) e o Jarvis diz "Bem-vindo de volta, senhor", resumindo o que aconteceu: timers que acabaram, mídia pausada, PC bloqueado e alguém que ele não reconheceu na frente do PC. O fim do timer é anotado quando ele é criado, então entra no resumo mesmo que a conversa já tenha fechado. Com a tela bloqueada, ele espera você desbloquear para falar.

### Saiu

Nem rosto nem teclado e mouse por 20 s. Teclado e mouse contam como presença, então olhar o monitor vertical de lado enquanto digita não vira "ausente".

### Fora por muito tempo

Depois de `JARVIS_PRESENCE_AWAY_MINUTES`, a mídia é pausada, mas só se algo estiver tocando: ele mede o nível de áudio dos apps no Windows antes de mandar a tecla play/pause, que alternaria. Com o bloqueio ligado, o PC bloqueia (`lock_workstation` do `pc_control.py`).

O painel Sistema mostra "Presente", "Ausente há 5 min", "Verificando..." ou o motivo de não estar observando.

Por voz: "liga a presença", "desliga a presença", "pode bloquear quando eu sair", "não bloqueia quando eu sair", "a presença está ligada?". O que muda por voz vale até reiniciar o Jarvis. O padrão fica no `.env`.

"Desliga a câmera" desliga a presença também, e ela não religa a webcam sozinha. Diga "liga a presença" para voltar.

### Reconhecer só você

É opcional. Com o Jarvis fechado (ele é o dono da câmera), rode:

```bash
python presence.py --enroll   # umas 30 amostras do seu rosto em 10 s; vire a cabeça devagar
python presence.py --test     # mostra rostos, "é você" ou "não reconheci" e a semelhança, ao vivo
python presence.py --forget   # apaga o cadastro
```

O MediaPipe (Face Landmarker) acha olhos, nariz e boca, o rosto é alinhado e o SFace do OpenCV (já vem no `opencv-contrib-python`) gera um embedding de 128 números. O cadastro guarda só esses vetores em `presenca_rosto.json` (fora do git), nunca imagens.

Com o cadastro, outra pessoa sentada não ganha "bem-vindo de volta" nem conta como você presente (o PC bloqueia normalmente), e o resumo avisa que apareceu alguém desconhecido. Semelhança de 0,363 para cima (o limite recomendado do SFace) é você. O `--test` mostra o valor para você conferir com outras pessoas e outras luzes. Isso não é trava de segurança: quem protege o PC é o bloqueio do Windows.

Na primeira execução são baixados para `.cache/models`, conferidos por hash, o detector de rosto (uns 230 KB) e, com cadastro, o Face Landmarker (3,7 MB) e o SFace (37 MB).

### Limitações

O detector é de curta distância, até uns 1,5 m da webcam. Com a presença ativa a webcam fica ligada o tempo todo, então a luz e o aviso CÂMERA ATIVA ficam acesos.

Os gestos rodam no processo do agente e ainda abrem a webcam por conta própria. No Windows, a segunda abertura pode falhar com "câmera em uso" enquanto os dois estiverem ligados.

### Como testar

1. `.env` com `JARVIS_ENABLE_CAMERA=true`, `JARVIS_PRESENCE=true`, `JARVIS_PRESENCE_AWAY_MINUTES=1` e `JARVIS_WAKE_SILENCE_SECONDS=30`, depois `python jarvis.py`. O painel Sistema deve mostrar "Presença · PRS-25: Presente" em uns 2 s, junto com o aviso CÂMERA ATIVA.
2. Vire a cabeça para o monitor vertical por 30 s mexendo no mouse: continua "Presente". Pare de mexer e saia da frente: depois de uns 20 s, "Ausente há menos de 1 min".
3. Deixe um vídeo do YouTube tocando, peça antes "timer de 2 minutos pro chá" e saia por 3 minutos. Em 1 minuto o vídeo pausa (e nada acontece se não houver som tocando).
4. Volte e sente: bipe, o link abre e o Jarvis diz "Bem-vindo de volta, senhor", citando o timer do chá e a mídia pausada. Saia por só 1 minuto e volte: sem boas-vindas.
5. "Pode bloquear quando eu sair" e saia por 2 minutos: o PC bloqueia. Ao voltar, as boas-vindas só vêm depois de desbloquear. Repare se a webcam continua mandando imagem com a tela bloqueada (o painel deve seguir "Ausente", sem erro).
6. "Não bloqueia quando eu sair" tira o "bloqueia ao sair" do painel. "Desliga a câmera" mostra "Câmera desligada · diga “liga a presença”", e "liga a presença" volta a observar.
7. Gestos juntos: "liga os gestos" com a presença ligada. Se der "câmera em uso", anote.
8. Opcional: feche o Jarvis, rode `python presence.py --enroll` e depois `--test`. Você deve ver "é você" com semelhança alta (0,6 ou mais), e outra pessoa (ou uma foto de outra pessoa no celular) deve dar "não reconheci" com valor baixo.
