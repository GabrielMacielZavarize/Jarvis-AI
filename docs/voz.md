# Voz

## Palavra de ativação

Protocolo WAK-22. Diga "Jarvis" e o link abre sozinho.

```env
JARVIS_WAKE_WORD=true
JARVIS_WAKE_THRESHOLD=0.5        # de 0.05 a 0.99; menor ativa mais fácil (e erra mais)
JARVIS_WAKE_SILENCE_SECONDS=0    # 0 = nunca fecha sozinho; 120 = fecha após 2 min de silêncio
JARVIS_WAKE_MIC=                 # opcional: parte do nome de um microfone só para o detector
```

Com isso, o `python jarvis.py` também sobe o `wake_word.py`, um processo leve (uns 110 MB de RAM e 2 ms de CPU a cada 80 ms de áudio) que roda o [openWakeWord](https://github.com/dscripka/openWakeWord) com o modelo pré-treinado `hey_jarvis`. Na primeira execução ele baixa uns 5 MB de modelos do GitHub do openWakeWord.

### Como funciona

Diga "Jarvis" ou "hey Jarvis", espere o bipe e fale. O HUD toca o bipe e conecta o link. Se nenhuma aba do HUD estiver aberta, o servidor abre o navegador e a aba conecta assim que carrega.

Com `JARVIS_WAKE_SILENCE_SECONDS` maior que 0, o link fecha com um bipe descendente depois desse tempo sem conversa e o detector volta a esperar a palavra. O Jarvis falando ou pensando conta como conversa. Nos últimos 10 segundos o dock mostra a contagem ("Encerrando por silêncio em 8 s"), e basta falar para continuar. O link não fecha enquanto houver timer correndo, código esperando "confirmar" ou instalação em andamento. Com a ativação ligada, essa regra vale também para links abertos pelo clique ou pelo Espaço e para um link em que o agente nunca respondeu. O padrão é 0: o link só fecha com "tchau, Jarvis" ou o botão.

O painel Sistema mostra o estado do detector: "Aguardando “Jarvis”", "Pausada durante o link", "Detector offline" ou "Sem sinal no microfone". Esse último aparece quando o microfone que ele abriu só entrega silêncio por 5 segundos, o que em geral quer dizer microfone mudo no Windows.

### Microfone

O detector usa o microfone escolhido no painel Sistema (o HUD passa o nome do dispositivo ao servidor) ou, sem escolha, o padrão do Windows. Durante o link ele libera o microfone e quem capta é o navegador. Assim os dois nunca disputam o dispositivo, e a voz do Jarvis saindo da caixa de som não reativa a palavra. Ele volta a ouvir 1,5 s depois de o link fechar.

Fone Bluetooth usado como microfone fica no modo viva-voz (áudio de ligação) enquanto o detector escuta. Para manter a música com qualidade, deixe o detector no microfone do notebook com `JARVIS_WAKE_MIC=Microphone Array` (ou outra parte do nome).

### Calibrando

`python wake_word.py --test` mostra o pico de cada fala e se ela ativaria com o limiar atual. Diga "Jarvis" e "hey Jarvis" algumas vezes e fale frases comuns para ver os falsos positivos. `python wake_word.py --list-mics` lista os microfones que o detector enxerga.

### Limitações

O modelo foi treinado com "hey jarvis" em inglês. "Hey Jarvis" e "Jarvis" com pronúncia inglesa (djár-vis) pontuam perto de 1, e "Jarvis" com pronúncia portuguesa pontua bem menos. Se o seu não ativar, calibre e baixe o `JARVIS_WAKE_THRESHOLD`.

O que você fala junto com a palavra ("Jarvis, que horas são?") não chega ao Jarvis, porque o link só abre depois dela. Espere o bipe.

Numa aba que o navegador abriu sozinho, sem nenhum clique, o Chrome pode bloquear o som. Nesse caso aparece o botão "Clique para ouvir o Jarvis".

Os modelos pré-treinados do openWakeWord são CC BY-NC-SA 4.0, ou seja, só para uso pessoal e não comercial.

No Linux o `openwakeword` depende do `tflite-runtime`, que não tem wheel para o Python 3.12. Lá, instale com `pip install openwakeword --no-deps` e depois `pip install onnxruntime tqdm requests`.

## Voz e persona

Protocolo VOZ-30.

`JARVIS_VOICE` escolhe uma das 30 vozes do Gemini Live. A padrão é Charon, grave, calma e informativa, a mais parecida com o Jarvis do filme. Outras que combinam: Orus (grave e firme), Iapetus (clara e serena), Rasalgethi (de narrador), Algieba (suave) e Sadaltager (culta). Um nome que não existe aparece como erro no `python doctor.py` e no painel Sistema.

```env
JARVIS_VOICE=Charon
```

Também dá para trocar falando:

- "Jarvis, quais vozes você tem?" Ele diz a atual e as recomendadas, e a lista completa aparece num painel.
- "Troca sua voz para Orus." Ele confirma com a voz antiga e já responde a próxima com a nova. O plugin do Gemini reabre a conexão num instante, sem perder a conversa. A escolha fica em `voz.json` (fora do git) e vale mais que o `.env` nas próximas sessões.
- "Volta pra sua voz normal." Apaga o `voz.json` e volta para a `JARVIS_VOICE`.

A troca falada só existe no Gemini Live. Na OpenAI, a voz é a de `OPENAI_VOICE`.

A persona está no `prompts.py`: mordomo britânico educado, que chama você de "senhor", fica calmo quando algo dá errado, tem humor seco e responde em no máximo duas frases.

Os sons da interface e as animações do núcleo estão em [hud.md](hud.md#sons-da-interface).

## Como testar

Use fone para ouvir bem os sons.

1. `python jarvis.py`, abra o HUD e confira no painel Sistema a linha "Voz · VOZ-30" (Charon) e, em Ajustes, "Sons da interface" ligado. Clique em Testar: três notas subindo.
2. Inicie o link: toca o som de abertura e a saudação vem no tom do mordomo ("Boa noite, senhor...").
3. "Como está o tempo em Lisboa?": bipe curto quando a ferramenta começa, anel girando e giroscópio no núcleo, bipe duplo e onda de choque no fim.
4. Uma pergunta que exige pensar ("explica em uma frase o que é fusão nuclear"): os arcos de varredura giram enquanto ele pensa.
5. "Quais vozes você tem?" (painel com a lista) e depois "troca sua voz para Orus": ele confirma e a resposta seguinte já sai na voz nova. Feche e reabra o link: continua Orus. "Volta pra sua voz normal" devolve a Charon.
6. "Timer de 10 segundos": no fim, três bipes de alarme.
7. Desligue os sons em Ajustes, recarregue a página (F5) e confira que continuam desligados. Religue, baixe o volume e repita o passo 3.
8. "Tchau, Jarvis": um único som de link fechando, mesmo com a palavra de ativação ligada.
9. Com `JARVIS_WAKE_WORD=true`, rode `python wake_word.py --test` com o Jarvis fechado e confira que "Jarvis" passa do limiar e frases comuns não. Depois suba o `jarvis.py`, diga "Jarvis" e veja o link abrir.
