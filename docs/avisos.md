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

### Tarefas do dia

Uma vez por dia, no primeiro momento útil da manhã, o Jarvis resume as [tarefas](dia-a-dia.md#tarefas-e-notas-tar-43) que pedem atenção: "2 tarefas atrasadas e 1 para hoje: fechar o relatório; pagar o boleto; ir ao dentista." Lista até três e diz quantas ficaram de fora. Sem tarefa atrasada nem para hoje, ele não avisa. Tarefa sem prazo e nota não entram.

"Momento útil" quer dizer, ao mesmo tempo:

- entre 5h e 12h. Quem liga o PC depois do meio-dia fica sem o aviso daquele dia;
- fora do horário de silêncio. Se o silêncio vai até as 7h, o aviso sai depois das 7h;
- com você na frente do PC, se a [presença](camera-e-presenca.md) estiver ligada com a câmera. Sem presença (ou com a câmera desligada), essa condição não existe e o aviso não trava.

O primeiro momento útil do dia gasta o aviso, mesmo que não houvesse tarefa: uma tarefa anotada às 10h não vira aviso das 10h. O dia fica registrado no `lembretes.json`, então reiniciar o Jarvis não repete.

A prioridade é normal: com o link aberto o Jarvis fala; com o link fechado o aviso fica só no HUD (não abre o navegador nem acorda o Jarvis, tarefa não é urgência). O assunto é `tasks`: "para de me avisar sobre tarefas" silencia o assunto (continua no HUD, sem voz). O monitor só existe com `JARVIS_ENABLE_DAY=true` (o padrão), já que as tarefas fazem parte do [Dia a dia](dia-a-dia.md).

### Certificados dos seus domínios

Uma vez por dia o Jarvis confere o certificado HTTPS dos domínios que você listar no `.env` ([Olho de Deus](olho-de-deus.md#vigia-de-certificados)):

```env
JARVIS_OSINT_WATCH_DOMAINS=meusite.com.br,loja.meusite.com.br
```

Avisa, num aviso só, os que vencem em menos de 14 dias ("loja.meusite.com.br vence em 9 dias"), os com certificado inválido ou vencido e os que não responderam (tenta duas vezes antes de dizer isso). Com tudo em ordem, não diz nada. A consulta passa pela mesma trava do Olho de Deus: só conecta em IP público.

- Prioridade normal para "vence em breve" (fala com o link aberto, HUD com o link fechado) e alta para inválido, vencido ou sem resposta (com o link fechado, acorda o Jarvis como um lembrete).
- Espera o horário de silêncio acabar e, com a presença ligada, você estar na frente do PC. Sem internet no PC ele não conclui nada (para não acusar o seu site à toa) e tenta de novo em 10 minutos.
- O dia da última conferência fica no `lembretes.json` (`certs_check_day`), então reiniciar o Jarvis não repete. Para conferir de novo no mesmo dia, troque esse valor por `null`.
- O assunto é `certs`: "para de me avisar sobre certificados" silencia a voz (continua no HUD).

### Troca de bloco do foco

A [sessão de foco](dia-a-dia.md#foco-foc-47) também avisa pelo motor, com o assunto `focus`: "Hora da pausa", "De volta ao foco", "Sessão de foco concluída" e, com a presença ligada, "Foco retomado" quando você volta. A prioridade é normal: com o link aberto o Jarvis fala; com o link fechado o aviso fica no HUD e, com o [ícone da bandeja](bandeja.md#avisos-do-jarvis-na-bandeja), vira notificação do Windows. Nunca abre o navegador. O assunto é `focus` ("para de me avisar sobre o foco"). Vale também com `JARVIS_PROACTIVE=false`: sem o motor, o aviso vai só para a bandeja e para a aba aberta.

## Como ele avisa

Quem vigia é o servidor do HUD, que sobe com o `jarvis.py` e fica de pé o tempo todo. Cada aviso tem uma prioridade:

| Link | Baixa ou normal (download, CPU, carregador, disco, tarefas) | Alta (lembrete, bateria em 20%) | Crítica (bateria em 10%, lembrete urgente) |
| --- | --- | --- | --- |
| Aberto | O Jarvis fala | O Jarvis fala | O Jarvis fala |
| Fechado | Aviso no HUD | Abre o link pela mesma via do "Jarvis" e fala | Abre o link e fala |
| Horário de silêncio | Aviso no HUD | Aviso no HUD | Abre o link e fala |

Com o link aberto, o agente pergunta ao servidor a cada 2 s (`/api/proactive/next`) e espera você ou ele terminarem de falar antes de dar o aviso.

Com o link fechado, o aviso importante faz o mesmo que a palavra de ativação: bipe, a aba conecta sozinha (ou o servidor abre o navegador) e a primeira fala do Jarvis é o aviso, no lugar da saudação. Se `JARVIS_WAKE_SILENCE_SECONDS` for maior que 0, o link fecha de novo depois desse silêncio, mesmo sem a palavra de ativação ligada.

Os avisos que ficam só no HUD aparecem como notificação e painel "Aviso" e entram no registro de atividades. Se nenhuma aba estiver aberta, os últimos 10 esperam a próxima.

## Durante o foco

Enquanto um bloco de [foco](dia-a-dia.md#foco-foc-47) está correndo, o motor segura os avisos que não são críticos e os entrega quando o bloco acaba. Ficam de fora da espera:

| Passa na hora | Espera o fim do bloco |
| --- | --- |
| Crítica: bateria em 10%, lembrete marcado como urgente | Alta: lembrete comum, bateria em 20% |
| A troca de bloco do próprio foco | Normal e baixa: download, CPU e RAM, disco, tarefas, erros na janela vigiada, carregador |

- "Durante o bloco" vale também quando a contagem está parada pela ausência: você saiu, mas a sessão não acabou. Na pausa (o descanso), ao encerrar o foco e ao terminar a sessão, a espera acaba.
- O aviso que esperou sai pelo caminho de sempre, decidido na hora da entrega: um lembrete alto com o link fechado abre o link nessa hora, e o horário de silêncio e os assuntos silenciados continuam valendo. Ele ganha "(chegou às 14:02, durante o foco)" no fim. Vários avisos saem juntos, na ordem em que chegaram, no máximo 30 (passando disso, os mais antigos caem).
- Quem segura é o servidor, na memória: se o Jarvis for reiniciado no meio do bloco, o que esperava se perde. Um lembrete comum que vence durante o foco também espera (ele já saiu do `lembretes.json`), então um bloco de 3 horas pode atrasar um lembrete em até 3 horas. Para um lembrete que não pode esperar, peça como urgente.
- Sem o foco rodando, ou com `JARVIS_ENABLE_DAY=false`, nada é segurado.

## Por voz

"Para de me avisar sobre bateria" silencia o assunto, que continua aparecendo no HUD, sem voz. Os assuntos são bateria, desempenho (CPU e RAM), downloads, disco, lembretes, erros na tela, tarefas e foco. "Por duas horas" põe prazo, e "pode voltar a avisar da bateria" desfaz.

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
9. Tarefas: veja os itens de "Tarefas nos avisos proativos" no [roteiro de testes](ROTEIRO_DE_TESTES.md#tarefas-nos-avisos-proativos).
10. Foco: veja os itens de "Foco integrado" no [roteiro de testes](ROTEIRO_DE_TESTES.md#foco-integrado-com-presença-avisos-e-bandeja).
