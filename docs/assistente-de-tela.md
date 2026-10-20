# Assistente de tela

Protocolo TEL-31. Feito para o dia a dia de dev: "explica esse erro", "o que tem de errado aqui?", "o que esse código faz?", "resume essa página", "traduz isso" e "copia a correção".

Vem junto com o controle do PC (`JARVIS_ENABLE_PC_CONTROL=true`) e usa a `GOOGLE_API_KEY` com o modelo de `JARVIS_COMPUTER_USE_MODEL` (padrão `gemini-3.8-flash`, pela API normal, como o [MOU-20](mouse-e-ditado.md)), mesmo que a voz seja outro backend.

## O que ele lê

"Explica esse erro", "o que esse código faz?", "resume essa página" e "traduz isso" leem a janela em foco. "O que tem de errado aqui?" lê o trecho perto do cursor do mouse, umas 25 linhas acima e abaixo.

A ordem de leitura é:

1. O texto selecionado.
2. O texto da janela por UI Automation (Windows Terminal, navegador, VS Code, Bloco de Notas...).
3. Um print da janela, ou de uma região de uns 1100 por 650 pixels em volta do cursor, só quando não há texto.

O PhpStorm expõe pouco texto ao UI Automation, então lá costuma ir o print. Selecionar o trecho, ou copiar e dizer "explica o que eu copiei", dá a leitura mais precisa.

Se o HUD estiver em foco, o Jarvis lê a janela que está embaixo do mouse.

### Apontando com o dedo

Com os [gestos](gestos.md#apontar-e-falar) ligados, "aqui" é primeiro o lugar para onde você apontou com o indicador nos últimos 2,5 s, e só sem apontamento o cursor do mouse. O Jarvis lê a janela que está embaixo do ponto apontado, mesmo que outra esteja em foco, e ignora a seleção da janela em foco, porque você mostrou outro lugar. A resposta diz que usou o ponto apontado, e o painel mostra "texto onde você apontou" ou "print de onde você apontou".

As regras são as mesmas do cursor: apontar para um cofre de senhas não lê nada, apontar para o HUD pede para apontar para outra janela e os segredos continuam ocultados antes de o texto sair do computador. O ponto é só uma coordenada; nada novo é gravado ou enviado.

## O painel

O painel Assistente de tela mostra de onde leu (por exemplo "texto da janela · janela 'PowerShell'"), a causa, a correção, a explicação e os blocos de código com destaque de sintaxe (PHP, JS/TS, Python, SQL, shell, JSON, HTML, CSS) e botão Copiar. Por voz o Jarvis fala só o resumo. Código ele nunca lê em voz alta.

"Copia a correção" (ou "copia o segundo bloco") coloca o código na área de transferência do Windows. Ele nunca digita nem cola sozinho: você cola com Ctrl+V onde quiser.

Sem `GOOGLE_API_KEY`, ou se o modelo falhar, o texto lido vai para a própria sessão de voz responder, e o print, quando é o caso, vai como imagem.

## Fica de olho numa janela

Protocolo OLH-35. "Jarvis, fica de olho no terminal" liga um vigia: a cada 5 s o Jarvis lê o texto daquela janela, pela mesma UI Automation, sem prints, e procura erros nas linhas que apareceram desde a última leitura. Precisa do controle do PC e dos [avisos](avisos.md) ligados (`JARVIS_ENABLE_PC_CONTROL=true` e `JARVIS_PROACTIVE=true`).

| Você diz | O que ele vigia |
| --- | --- |
| "Fica de olho no terminal" | O terminal aberto mais recente (Windows Terminal, PowerShell, cmd, WSL, Git Bash) |
| "Fica de olho no PhpStorm" | A janela do PhpStorm. Vale qualquer app ou palavra do título: "no VS Code", "no UserController" |
| "Fica de olho nessa janela" | A janela em foco, ou a que está embaixo do mouse quando o HUD está em foco |

Ele vigia uma janela por vez. Pedir outra troca a vigiada. Vale o mesmo limite da leitura: o editor do PhpStorm expõe pouco texto ao UI Automation, então o terminal é o lugar onde o vigia funciona melhor. Se a janela não mostrar texto nenhum, o Jarvis avisa ao ligar.

Contam como erro novo:

| Tipo | Exemplos |
| --- | --- |
| Exceção | Traceback do Python (pela linha final), `TypeError: ...`, `Exception in thread "main"`, promise rejeitada |
| Erro do PHP | `PHP Fatal error`, `Parse error`, `Uncaught ...Exception` |
| Teste falhando | `FAILED tests/...` do pytest, `FAILURES!` do PHPUnit, `Tests: 1 failed` do Jest |
| Erro de build | `error TS2322`, `npm ERR!`, `ERROR in` do webpack, `BUILD FAILED`, erros do make e do cargo |

Código que só fala de erro, como `catch (Exception $e)` ou `throw new Error(...)`, não conta. O que já estava na tela quando o vigia ligou também não.

Quando aparece um erro, sai um aviso pelo caminho dos avisos proativos, com prioridade normal. Com o link aberto o Jarvis diz onde apareceu e pergunta "quer que eu explique esse erro?". "Sim" chama o `explain_screen` sobre a janela vigiada, mesmo que ela esteja atrás de outra, e o painel Assistente de tela mostra a explicação de sempre. Com o link fechado, no horário de silêncio ou com o assunto silenciado ("para de me avisar dos erros"), o aviso fica só no HUD.

O mesmo erro avisa uma vez só por vigia, mesmo que você rode de novo e ele volte em outra linha. Entre dois avisos ficam pelo menos 20 s. Se vários erros aparecem juntos, o aviso cita o primeiro, que costuma ser a causa.

"Para de vigiar" desliga. Ele também para sozinho quando a janela fecha, depois de 30 minutos sem o texto mudar ou se a janela virar uma das que nunca são lidas. Nesses casos aparece um aviso só no HUD. "Que janela você está vigiando?" diz qual é, há quanto tempo e quantos erros avisou.

O texto passa pelo mesmo filtro de segredos antes de qualquer coisa, e nada é gravado em disco. Quem vigia é o servidor do HUD, então o vigia continua com o link fechado.

## Leitura de tela simples

Fora do assistente existe o `look_at_screen` (VIS-14): "o que tem aberto no PhpStorm?" tira um print do monitor ou da janela, mostra no HUD e manda para o Gemini analisar.

O que sai do computador em cada caso, e o que é ocultado antes, está em [seguranca.md](seguranca.md#leitura-de-tela).

## Como testar

1. `python jarvis.py --rebuild`, conecte e confira o TEL-31 no painel Protocolos.
2. No PowerShell, rode `python -c "import json; json.loads('{')"`. Com o terminal em foco: "Jarvis, explica esse erro". Deve aparecer o painel com "texto da janela", a causa (`JSONDecodeError`) e a correção.
3. Com o mouse em cima da mensagem de erro e o HUD em foco: "o que tem de errado aqui?". Deve vir "texto perto do cursor" (ou "print perto do cursor") e a leitura da janela certa, inclusive no monitor vertical.
4. No PhpStorm, selecione uma função PHP: "o que esse código faz?". Deve vir "texto selecionado". Sem seleção, "print da janela".
5. "Copia a correção" e cole com Ctrl+V num arquivo de rascunho: tem que vir exatamente o bloco 1 do painel, sem nada digitado pelo Jarvis. Teste também o botão Copiar.
6. Numa página em inglês: "resume essa página" e depois "traduz isso" com um parágrafo selecionado.
7. Abra o `.env` no Bloco de Notas e peça "explica isso": o painel avisa que ocultou segredos e a chave não aparece em lugar nenhum.
8. Com o KeePass ou o Bitwarden em foco, o Jarvis se recusa a ler.
9. Com os gestos ligados, aponte para o erro em outro monitor e diga "explica isso aqui": deve vir "texto onde você apontou", sem o mouse sair do lugar. Os passos completos estão em [gestos.md](gestos.md#apontar-e-falar-1).
10. Vigia: veja a seção 22 do [roteiro de testes](ROTEIRO_DE_TESTES.md#22-fica-de-olho-no-terminal).
