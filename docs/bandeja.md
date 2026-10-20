# Ícone na bandeja

No Windows o Jarvis pode ficar só como um ícone ao lado do relógio, sem a janela do terminal aberta. O ícone mostra o estado e tem um menu para o dia a dia. O código do recurso é BAN-41.

## Ligando

```powershell
pythonw jarvis.py --tray
```

O `pythonw` é o Python sem janela de console. Com `python jarvis.py --tray` o ícone aparece do mesmo jeito e o terminal continua mostrando tudo.

Para ligar sempre, ponha no `.env`:

```env
JARVIS_TRAY=true
```

No Linux e no macOS o `--tray` e o `JARVIS_TRAY` são ignorados com um aviso, e o Jarvis sobe como sempre.

## O que o ícone mostra

| Cor do ícone | Estado |
| --- | --- |
| Cinza | Servidor do HUD parado ou ainda subindo |
| Amarelo | Servidor ok, mas o agente de voz caiu |
| Anel azul | Pronto, link fechado |
| Anel azul com o centro aceso | Pronto e ouvindo a palavra de ativação |
| Verde | Link aberto, em conversa |

Parando o mouse sobre o ícone aparece o resumo: servidor, agente, link, palavra de ativação e gestos.

## O menu

Clique com o botão direito no ícone. Dois cliques com o esquerdo abrem o HUD.

| Item | O que faz |
| --- | --- |
| Abrir o HUD | Abre `http://127.0.0.1:8000` no navegador |
| Iniciar o link | Abre o link na aba do HUD, como dizer "Jarvis". Sem aba aberta, abre o navegador antes |
| Encerrar o link | Fecha o link na aba em conversa, como o botão Encerrar link |
| Gestos | Liga e desliga os gestos das mãos. Só aparece ativo com `JARVIS_ENABLE_GESTURES=true` ou `--gestures` |
| Iniciar com o Windows | Liga e desliga o Jarvis no login do Windows |
| Abrir a pasta de logs | Abre a pasta `logs` no Explorer |
| Reiniciar o Jarvis | Fecha tudo e sobe de novo com as mesmas opções, sem abrir outra aba do navegador |
| Sair | Fecha o servidor, o agente, o detector e o ícone |

O resultado de cada item aparece numa notificação do Windows quando há algo a dizer ("Nenhum link aberto", "Gestos ligados").

Os gestos do menu rodam no processo do `jarvis.py`. Se você ligou os gestos por voz ("Jarvis, liga os gestos"), desligue também por voz: os dois juntos disputam a webcam.

## Iniciar com o Windows

O item grava a entrada `Jarvis` em `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`:

```
"C:\...\.venv\Scripts\pythonw.exe" "C:\...\Jarvis-AI\jarvis.py" --tray --no-browser
```

Não precisa de administrador e vale só para o seu usuário. A entrada aparece também em Configurações, Aplicativos, Inicialização, e no Gerenciador de Tarefas. Se você mover a pasta do projeto ou recriar o venv, o próximo `--tray` corrige o caminho sozinho.

Escolhemos a chave Run em vez de um atalho em `shell:startup` porque ela não precisa de COM nem de arquivo `.lnk`, liga e desliga numa operação só e é fácil de testar.

## Logs

Com o ícone ligado, ou sempre que o Jarvis roda pelo `pythonw`, tudo o que iria para o terminal vai para `logs/jarvis.log`, na pasta do projeto:

| O quê | Como aparece no log |
| --- | --- |
| Mensagens do `jarvis.py` e do servidor | `[jarvis]` |
| Erros e avisos | `[jarvis.erro]` |
| Agente de voz | `[jarvis.agente]` |
| Detector da palavra de ativação | `[jarvis.ativacao]` |

O arquivo vira `jarvis.log.1` ao passar de 1 MB, e ficam só os 5 mais recentes. A pasta `logs/` está no `.gitignore`.

## Por que Win32 puro

O ícone usa `Shell_NotifyIconW` pelo `ctypes`, como o aviso dos gestos (`gesture_overlay.py`), e o desenho é feito pelo Pillow, que já vem com as dependências. O `pystray` faria o mesmo com menos código, mas seria uma dependência nova só para o Windows, e o projeto já sabe falar com o Win32. Sem o Pillow o ícone fica com o desenho padrão do Windows e o resto funciona igual.

## Como funciona

| Peça | Arquivo |
| --- | --- |
| Estado, menu, comandos, chave Run e logs | `tray.py` |
| Ícone, menu e notificações no Windows | `tray_icon.py` |
| Rotas `/api/tray/state` e `/api/tray/link` | `tray.py`, ligadas no `server.py` |
| Abrir e fechar o link na aba | `web/src/hooks/useWakeWord.ts` |

A cada 2 segundos o ícone pergunta ao servidor se há link aberto e se o detector está ouvindo, e confere se o processo do agente está vivo. Para abrir e fechar o link ele usa o mesmo canal da palavra de ativação: o servidor manda um aviso à aba do HUD, e é ela que conecta ou desconecta.
