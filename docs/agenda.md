# Google Agenda

Protocolo AGD-27. O Jarvis lê e mexe na sua agenda principal do Google. Ler não pede nada. Criar, alterar e apagar seguem o mesmo esquema do email: a ferramenta prepara a mudança, mostra um código no painel Agenda e só grava quando você diz "confirmar agenda" e o código.

```env
JARVIS_ENABLE_CALENDAR=true
JARVIS_CALENDAR_REMINDER_MINUTES=10   # aviso antes de cada reunião; 0 = sem aviso
```

## Login no Google (uma vez só)

O acesso é do tipo "app para computador": nenhuma senha vai para o `.env`, e o token fica só no seu PC.

1. Abra o [Google Cloud Console](https://console.cloud.google.com/) e crie um projeto (por exemplo `Jarvis`).
2. Em APIs e serviços > Biblioteca, procure Google Calendar API e clique em Ativar.
3. Em APIs e serviços > Tela de consentimento OAuth (ou "Google Auth Platform"), escolha o tipo Externo e preencha o nome do app e o seu email. Em Público-alvo > Usuários de teste, adicione o seu Gmail. O app pode ficar "Em teste" para sempre, já que só você usa.
4. Em Credenciais > Criar credenciais > ID do cliente OAuth, escolha App para computador e crie.
5. Clique em Baixar JSON e salve como `google_credentials.json` na pasta do projeto, ao lado do `jarvis.py`.
6. Rode `python calendar_tools.py --login`. O navegador abre, você escolhe a conta, passa pelo aviso "o Google não verificou este app" (Continuar, ou Avançado > Acessar Jarvis) e autoriza a agenda. O token vai para o `google_token.json` e se renova sozinho.

Os dois arquivos estão no `.gitignore`. `python calendar_tools.py --hoje` testa a conexão, e `--logout` apaga o token (revogue também em [myaccount.google.com/permissions](https://myaccount.google.com/permissions)). A permissão pedida é só `calendar.events`, sem acesso a outros dados da conta.

## Como falar

As datas são entendidas em português, no fuso `America/Sao_Paulo`.

| Você fala | Ferramenta |
| --- | --- |
| "O que eu tenho hoje?", "e amanhã?", "e sexta?", "e essa semana?" | `get_agenda`. O resumo é falado e a lista completa fica no painel |
| "Qual minha próxima reunião?" | `next_meeting`. Diz quanto falta e oferece abrir o link do Meet |
| "Marca dentista sexta às 15h", "marca reunião com o Pedro depois de amanhã às 9 por meia hora", "marca o aniversário da Ana dia 25 o dia inteiro" | `prepare_calendar_event`. Avisa se conflita com outro evento |
| "Passa o dentista para as 16h", "muda o almoço para amanhã" | `prepare_calendar_update`. Um horário sozinho mantém o dia, e a duração é mantida |
| "Desmarca a reunião das 10", "cancela o dentista de sexta" | `prepare_calendar_delete`. Sem dia, procura de hoje até a semana que vem. Se vários eventos combinarem, pergunta qual |

Formatos aceitos: hoje, amanhã, depois de amanhã, segunda a domingo (sozinho é a próxima ocorrência, contando hoje; "próxima sexta" pula hoje; "sexta da semana que vem"), dia 25, 25/12, 3 de novembro, daqui a 2 horas, 15h, 15h30, 15:30, às 9 e meia, 3 da tarde e meio-dia.

"Às 3" sem "da manhã" vira 15h: de 1 a 6 sem período conta como tarde. Um horário que já passou hoje, sem dia dito, vai para amanhã. Na dúvida, confira o dia e a hora que o Jarvis repete antes de confirmar.

## Aviso antes das reuniões

Com `JARVIS_CALENDAR_REMINDER_MINUTES` maior que 0, o servidor do HUD olha a agenda a cada minuto. Alguns minutos antes de um evento com horário, ele põe o aviso numa fila e acorda o HUD pelo mesmo caminho da palavra de ativação. Se não houver link, a aba conecta sozinha (e o servidor abre o navegador se nenhuma estiver aberta). Com o link aberto, o agente busca a fila em até 15 s. O Jarvis então avisa em uma frase ("Senhor, a Daily começa em 10 minutos") e oferece abrir o link da chamada.

Eventos de dia inteiro e convites recusados não geram aviso, e cada evento avisa uma vez só.

## Usando em outros módulos

O `calendar_tools` tem funções simples, sem voz:

- `eventos_de_hoje()`, `eventos_do_dia(data, dias=1)` e `proximo_evento()` levantam `CalendarError` se não houver login.
- `resumo_do_dia()` devolve uma frase pronta e nunca levanta erro, bom para o bom dia das rotinas.
- `ReminderWatcher(lead_minutes=10).check()` devolve os eventos que acabaram de entrar na janela de aviso, para quem quiser avisar de outro jeito.

## Como testar

1. Com o `google_credentials.json` salvo, rode `python calendar_tools.py --login` e depois `python calendar_tools.py --hoje`. Deve listar os eventos de hoje.
2. Ponha `JARVIS_ENABLE_CALENDAR=true` no `.env`, rode `python jarvis.py --rebuild` e confira no `python doctor.py` a linha "Google Agenda (AGD-27): ativado, conectado".
3. "Jarvis, o que eu tenho hoje?": resumo falado e painel Agenda com os horários certos (compare com o calendar.google.com). Teste também "e amanhã?" e "e sexta?".
4. "Qual minha próxima reunião?": título, horário e quanto falta.
5. "Marca dentista sexta às 15h": o Jarvis repete "sexta, dia X, das 15:00 às 16:00" e fala o código. Diga "pode marcar": não pode gravar. Diga "confirmar agenda" e o código: o evento aparece no Google Agenda, inclusive no celular.
6. "Passa o dentista para as 16h" e confirme: o evento muda de horário no Google. "Desmarca o dentista" e confirme: some.
7. "Marca um teste daqui a 12 minutos", confirme, feche o link e espere. Uns 10 minutos antes a aba conecta sozinha e o Jarvis avisa. Repita com o HUD fechado (o navegador deve abrir) e com o link aberto.
8. Rode `python calendar_tools.py --logout` e pergunte a agenda: o Jarvis deve explicar que falta o login.
