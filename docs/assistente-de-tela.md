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

## O painel

O painel Assistente de tela mostra de onde leu (por exemplo "texto da janela · janela 'PowerShell'"), a causa, a correção, a explicação e os blocos de código com destaque de sintaxe (PHP, JS/TS, Python, SQL, shell, JSON, HTML, CSS) e botão Copiar. Por voz o Jarvis fala só o resumo. Código ele nunca lê em voz alta.

"Copia a correção" (ou "copia o segundo bloco") coloca o código na área de transferência do Windows. Ele nunca digita nem cola sozinho: você cola com Ctrl+V onde quiser.

Sem `GOOGLE_API_KEY`, ou se o modelo falhar, o texto lido vai para a própria sessão de voz responder, e o print, quando é o caso, vai como imagem.

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
