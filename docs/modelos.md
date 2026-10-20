# Modelos, cota e tempo de resposta

O plano gratuito do Gemini dá conta do dia a dia, mas tem dois problemas: cada modelo tem a sua cota, e em horário de pico o modelo fica sobrecarregado e demora. O Jarvis lida com isso trocando de modelo no meio da conversa e mostrando quanto cada resposta levou.

```env
GOOGLE_FALLBACK_MODELS=gemini-3.1-flash-live-preview,gemini-2.5-flash-native-audio-preview-12-2025
JARVIS_MODEL_ROTATION=fallback   # fallback ou rotate
JARVIS_END_OF_SPEECH_MS=0        # 0 usa o padrão do Google; 500 responde mais cedo
JARVIS_WAKE_SILENCE_SECONDS=0    # 0 = o link nunca fecha sozinho
```

## Modelos de reserva

Quando o modelo em uso estoura a cota, fica sobrecarregado ou deixa de existir para a sua chave, a conversa passa para o próximo de `GOOGLE_FALLBACK_MODELS` sem derrubar o link. O histórico vai junto e, se a sua última fala ficou sem resposta, ele responde. O painel Sistema mostra "Modelo · reserva" e uma notificação diz o motivo.

O modelo que falhou fica de castigo em `modelos.json` (fora do git), por um tempo que depende do erro:

| Motivo | Pausa |
| --- | --- |
| Cota por minuto | 30 min |
| Cota diária | Até a meia-noite no horário do Pacífico, quando o Google zera a cota |
| Sobrecarga | 5 min |
| Modelo indisponível para a chave | 6 h |

`python doctor.py` mostra a fila e quem está em pausa. `GOOGLE_FALLBACK_MODELS=` vazio desliga a troca. Se a chave tiver faturamento ativo, confira o preço de cada modelo antes de deixá-lo na lista.

## Rodízio

Com `JARVIS_MODEL_ROTATION=rotate`, cada link novo começa pelo próximo modelo da lista, e o uso fica dividido entre eles. O padrão, `fallback`, sempre começa pelo `GOOGLE_MODEL`, que costuma ser o melhor, e só troca quando ele falha.

## Sessões longas

Sem ajuda, o Gemini Live derruba a sessão de áudio perto dos 15 minutos. O Jarvis liga a compressão de contexto (janela deslizante), então a conversa passa disso sem problema. Quando o Google renova a conexão, mais ou menos a cada 10 minutos, o plugin do LiveKit retoma a sessão sozinho.

## Link sempre aberto

Por padrão o link só fecha quando você diz "tchau, Jarvis" ou clica em Encerrar link. Só que o link aberto gasta minutos do LiveKit e cota do Gemini mesmo calado. Para economizar, use a palavra de ativação com `JARVIS_WAKE_SILENCE_SECONDS=120` (ou mais): o link fecha depois desse silêncio e um "Jarvis" abre de novo. Veja [voz.md](voz.md#palavra-de-ativação).

## Tempo de resposta

O painel Sistema mostra quanto o Jarvis levou do fim da sua fala até a primeira palavra (verde até 1,5 s, âmbar até 3 s, vermelho acima) e a média dos últimos 10 turnos. O terminal do agente registra o mesmo, assim: `Resposta em 1,2 s (gemini-3.8-live)`. Ferramentas que vão à internet, como clima e pesquisa, entram nessa conta, e a placa sobre o núcleo mostra quando é uma delas.

O Gemini espera um silêncio para decidir que você terminou de falar. Se as respostas demoram a começar, teste `JARVIS_END_OF_SPEECH_MS=500`. Se ele passar a cortar você no meio da frase, suba para 900. Aceita de 200 a 3000, ou 0 para o padrão do Google.

Continua lento? Veja [O Jarvis demora para responder](problemas.md#o-jarvis-demora-para-responder).

## Histórico

O painel Saúde do HUD guarda o tempo de resposta de cada turno, as pausas de cada modelo e as trocas no meio da conversa. Quando o tempo piora de um dia para o outro ou um modelo pausa por cota toda hora, ele sugere o ajuste. Veja [saude.md](saude.md).
