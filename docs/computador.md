# Computador

Com `JARVIS_ENABLE_PC_CONTROL=true` o Jarvis abre e fecha apps, sites, YouTube e streamings, mexe nas abas do navegador, controla mídia e volume, abre pastas, tira print, bloqueia a tela e organiza as janelas nos monitores. É um conjunto fechado de ações: ele não tem terminal nem roda comandos livres. As regras estão em [seguranca.md](seguranca.md#controle-do-computador).

## Monitores

As telas têm os mesmos números do botão Identificar das Configurações do Windows (Sistema > Tela), e não os de `\\.\DISPLAYn`, que o Windows numera de outro jeito. Como o Windows não documenta essa numeração, o Jarvis a estima pela ordem dos caminhos do `QueryDisplayConfig`: adaptador, depois tipo de conexão (tela interna, DisplayPort, HDMI), depois o conector. É a mesma heurística do módulo DisplayConfig. No meu setup isso dá tela 1 = notebook, tela 2 = monitor vertical (DisplayPort) e tela 3 = monitor de cima (HDMI), igual ao Identificar. Se algum número não bater, diga "a tela 1 é o notebook" (ou "os números estão certos" para confirmar) e a correção fica guardada.

Cada tela também tem um nome, tirado do hardware e da posição: notebook (tela embutida), vertical (em retrato), de cima, de baixo, da esquerda, da direita e horizontal. O nome só vale quando identifica uma tela só. Dá para criar apelidos: "salva a tela vertical como tela de código". Toda ferramenta que recebe um monitor (abrir app, site, YouTube, mover janela, ler a tela, layouts) aceita o número ou qualquer nome, e as respostas dizem os dois: "agora está no monitor de cima (tela 3)".

## Layouts de janelas

Um layout guarda, para cada janela visível, o app, o título, a tela (pelo hardware, então continua certo se você trocar os monitores de lugar), a posição e se estava maximizada.

Ao aplicar, o Jarvis abre pelo Menu Iniciar os apps que não estão abertos (com as mesmas travas do `open_app`), reposiciona cada janela e conta o que ficou faltando. Sites, pastas e janelas extras de um app já aberto não são reabertos.

Aplicar um layout, juntar tudo numa tela, mover as janelas de uma tela para outra e mostrar a área de trabalho podem ser desfeitos de uma vez com "desfaz". A janela do navegador com o HUD nunca é movida nem minimizada por essas ações em lote.

A numeração confirmada e os apelidos ficam em `telas.json`, e os layouts em `layouts.json`. Os dois ficam fora do git e podem ser editados à mão.

## Mídia

A regra aqui é não mentir: cada ferramenta diz ao modelo o que de fato aconteceu ("abri", "está tocando", "só abri a busca"), e o prompt proíbe dizer que algo está tocando sem confirmação.

### YouTube

O `play_youtube` lê os resultados da busca e abre o primeiro vídeo, dizendo o título e o canal reais e se está ao vivo. Abrir a página não garante que o áudio começou, então o Jarvis diz "abri".

### Lives

Com `live=true`, ou pedidos como "a live do Gaules", ele usa o filtro Ao vivo da busca do YouTube (`sp=EgJAAQ==`) e só aceita resultados com o selo AO VIVO, preferindo o canal com o nome pedido. Se ninguém estiver ao vivo, não abre nada e consulta a página pública do canal na Twitch para oferecer a alternativa (ao vivo, reprise ou offline).

### Twitch

`open_streaming("Twitch", "gaules")` abre o canal e diz se está ao vivo, em reprise (RERUN) ou offline. Se o canal não existir, abre a busca da Twitch.

### Spotify

`open_streaming("Spotify", "Guns N' Roses")` funciona sem conta de desenvolvedor nem chave. O Jarvis acha o link da faixa ou do álbum numa pesquisa web (`site:open.spotify.com`), abre `spotify:track:...` ou `spotify:album:...` no app desktop e confere o título da janela do Spotify, que mostra "Artista - Música" enquanto toca. Se o app abriu pausado, ele manda play só para a janela do Spotify (`WM_APPCOMMAND`) e confere de novo. Se começar a tocar outra coisa, pausa e avisa. Sem o app instalado, abre o Spotify Web e avisa que é preciso apertar play.

### Fechar não é pausar

O Jarvis guarda o título do último conteúdo que abriu. "Fecha a aba de reprodução" fecha essa aba pelo título exato (`browser_tab`), mesmo com várias abas do YouTube abertas. Se o último conteúdo foi o app do Spotify, ele usa o `close_app`. O `media_control` só pausa, retoma ou pula.

## Instalar aplicativos

```env
JARVIS_ENABLE_APP_INSTALL=true
```

Precisa do `winget`, que vem com o Windows 11 (senão, instale o "App Installer" pela Microsoft Store). Peça "instala o VLC pra mim": o Jarvis busca no winget e na Microsoft Store, mostra os candidatos no painel APP-15, prepara o pacote escolhido e fala um código de 6 dígitos. A instalação só começa quando você diz "confirmar instalação" e o código. As regras estão em [seguranca.md](seguranca.md#instalação-de-aplicativos).
