# Avisos e lembretes

Protocolo PRO-28. O Jarvis passa a avisar sozinho, na hora certa.

```env
JARVIS_PROACTIVE=true
JARVIS_QUIET_HOURS=23:00-07:00   # horário de silêncio: só o crítico fala; "off" desliga
JARVIS_DOWNLOADS_DIR=            # opcional: outra pasta para vigiar (vazio = Downloads do Windows)
```

## O que ele vigia

### Lembretes com hora

"Me lembra amanhã às 10h de ligar pro contador", "daqui a 2 horas me lembra de tirar a roupa da máquina", "segunda às 9", "dia 25 às 8", "hoje à noite". Os lembretes ficam no `lembretes.json` (fora do git) e sobrevivem a reinícios. Se o PC estava desligado na hora, o aviso sai quando o Jarvis voltar, dizendo o horário original.

"Quais lembretes eu tenho?" lista, também num painel do HUD. "Cancela o lembrete do contador" ou "desmarca o próximo" cancelam. Dizer que "é urgente" faz o lembrete falar mesmo no horário de silêncio.

O `set_timer` continua sendo a contagem curta da conversa atual.

### Bateria

Carregador desconectado, bateria em 20% (prioridade alta) e em 10% fora da tomada (crítica). Depois de carregar, volta a avisar.

### CPU e RAM

Acima de 90% por 5 minutos, citando o processo culpado. Os processos são somados pelo nome, então as dezenas de processos do Chrome contam como um. No máximo um aviso a cada 30 minutos.

### Downloads

Download concluído na pasta Downloads (a de verdade do Windows, mesmo se você a mudou de disco). Ele espera o `.crdownload` ou o `.part` sumir e o tamanho parar de mudar. Vários downloads juntos viram um aviso só.

### Disco

Menos de 10% livre (normal) ou de 3% (alta), em cada disco fixo, no máximo a cada 12 horas.

### Erros na janela vigiada

Com o controle do PC ligado, "fica de olho no terminal" faz o Jarvis avisar quando aparece um erro novo naquela janela e oferecer a explicação. Prioridade normal: fala com o link aberto e fica só no HUD com o link fechado ou no silêncio. O assunto é `watch` ("para de me avisar dos erros"). Detalhes no [OLH-35](assistente-de-tela.md#fica-de-olho-numa-janela).

## Como ele avisa

Quem vigia é o servidor do HUD, que sobe com o `jarvis.py` e fica de pé o tempo todo. Cada aviso tem uma prioridade:

| Link | Baixa ou normal (download, CPU, carregador, disco) | Alta (lembrete, bateria em 20%) | Crítica (bateria em 10%, lembrete urgente) |
| --- | --- | --- | --- |
| Aberto | O Jarvis fala | O Jarvis fala | O Jarvis fala |
| Fechado | Aviso no HUD | Abre o link pela mesma via do "Jarvis" e fala | Abre o link e fala |
| Horário de silêncio | Aviso no HUD | Aviso no HUD | Abre o link e fala |

Com o link aberto, o agente pergunta ao servidor a cada 2 s (`/api/proactive/next`) e espera você ou ele terminarem de falar antes de dar o aviso.

Com o link fechado, o aviso importante faz o mesmo que a palavra de ativação: bipe, a aba conecta sozinha (ou o servidor abre o navegador) e a primeira fala do Jarvis é o aviso, no lugar da saudação. Se `JARVIS_WAKE_SILENCE_SECONDS` for maior que 0, o link fecha de novo depois desse silêncio, mesmo sem a palavra de ativação ligada.

Os avisos que ficam só no HUD aparecem como notificação e painel "Aviso" e entram no registro de atividades. Se nenhuma aba estiver aberta, os últimos 10 esperam a próxima.

## Por voz

"Para de me avisar sobre bateria" silencia o assunto, que continua aparecendo no HUD, sem voz. "Por duas horas" põe prazo, e "pode voltar a avisar da bateria" desfaz.

"Horário de silêncio das 22h às 6h" ou "desliga o horário de silêncio" mudam o horário. O que você fala vale mais que o `.env` e fica guardado no `lembretes.json`.

"O que você está vigiando?" resume tudo.

## Limitações

Sem o servidor do HUD (só `python agent.py console`) os lembretes não disparam. Eles ficam guardados até o `jarvis.py` subir de novo.

O horário entendido é sempre repetido na resposta. Se o Jarvis entender errado, cancele e peça de novo, por exemplo "amanhã às 10h".

## Como testar

No Windows, com `JARVIS_PROACTIVE=true` e `python jarvis.py --rebuild`:

1. Lembrete com o link aberto: "Jarvis, daqui a 2 minutos me lembra de beber água". Ele repete o horário. Fique quieto: até uns 7 s depois da hora ele fala o lembrete. Depois, "quais lembretes eu tenho?" deve mostrar a lista vazia.
2. Lembrete com o link fechado: marque um para daqui a 3 minutos e encerre o link ("tchau, Jarvis"). Na hora, o HUD toca o bipe, conecta sozinho e a primeira fala é o lembrete, sem "Bom dia, senhor". Repita com a aba do HUD fechada: o navegador deve abrir sozinho.
3. Reinício: marque um para daqui a 5 minutos, feche o `jarvis.py` (Ctrl+C) e suba de novo. O lembrete continua no `lembretes.json` e dispara. Se estiver desligado na hora, ele avisa ao voltar, dizendo "era para...".
4. Cancelar: "me lembra amanhã às 10h de ligar pro contador" e depois "cancela o lembrete do contador".
5. Carregador: no notebook, tire o carregador com o link aberto e ele fala "Carregador desconectado". Com o link fechado, só aparece o aviso no HUD, sem voz. Diga "para de me avisar sobre bateria", recoloque e tire de novo: só aparece no HUD.
6. Download: baixe um PDF pelo Chrome e outro pelo Firefox. Deve vir um aviso por download, só depois de terminar (nada enquanto o `.crdownload` ou o `.part` existir).
7. CPU: rode algo pesado por mais de 5 minutos (um benchmark, ou `python -c "while True: pass"` em vários terminais). O aviso cita o processo culpado.
8. Silêncio: "horário de silêncio de agora até daqui a uma hora" (por exemplo "das 15h às 16h") e repita o passo 5: só HUD. Um lembrete urgente nesse horário ainda fala. No fim, "desliga o horário de silêncio".
