# Integrações MCP

Protocolo MCP-32. Pelo MCP (Model Context Protocol), o Jarvis usa as ferramentas de servidores prontos: GitHub, Notion, Spotify e qualquer outro serviço que tenha um servidor MCP. Cada serviço novo é uma entrada no `mcp.json`, sem escrever uma ferramenta para ele.

```env
JARVIS_ENABLE_MCP=true
JARVIS_MCP_TIMEOUT=8          # segundos que cada servidor tem para conectar quando o link abre
GITHUB_MCP_TOKEN=seu-token    # o mcp.json guarda só o nome desta variável
```

O cliente vem do extra `livekit-agents[mcp]`, que já está no `requirements.txt`. Se o seu ambiente é de antes, rode `python -m pip install -r requirements.txt` de novo.

## O mcp.json

Copie o `mcp.example.json` para `mcp.json`, na pasta do projeto. Ele fica fora do git.

```json
{
  "github": {
    "url": "https://api.githubcopilot.com/mcp/",
    "token_env": "GITHUB_MCP_TOKEN",
    "permitir": ["list_issues", "issue_read", "search_issues"]
  },
  "notion": {
    "comando": "npx",
    "args": ["-y", "@notionhq/notion-mcp-server"],
    "token_env": "NOTION_TOKEN",
    "permitir": []
  }
}
```

O Notion começa com o `permitir` vazio, então nada dele chega ao Jarvis ainda: veja abaixo como descobrir os nomes das ferramentas e escolha as que quer liberar.

| Campo | O que é |
| --- | --- |
| `url` | Servidor HTTP. Precisa ser `https://`, e `http://` só vale para `127.0.0.1` e IPs da rede de casa (`192.168.x.x`...) |
| `comando` e `args` | Servidor local, que o agente inicia (como o `npx` do Notion) |
| `token_env` | Nome da variável do `.env` com o token. No HTTP ele vai como `Authorization: Bearer`; no servidor local, como variável de ambiente com esse mesmo nome |
| `permitir` | As ferramentas que o Jarvis pode usar. Sem essa lista, nada do servidor é liberado |
| `confirmar` | Ferramentas que pedem código mesmo parecendo de leitura |
| `sem_confirmar` | Ferramentas que não pedem código mesmo parecendo de escrita. Use só para coisas que você não se importa de rodar sem querer, como dar play numa música |
| `nome` | Como o serviço aparece no HUD e na fala. O padrão já conhece GitHub, Notion, Spotify, Slack, Linear e Home Assistant (`home_assistant`) |

Chaves que começam com `_` são ignoradas e servem de comentário. Um campo desconhecido (por exemplo um `token` com o valor) faz o arquivo ser recusado: o segredo fica no `.env`.

Para descobrir os nomes das ferramentas, rode:

```bash
python mcp_client.py
```

Ele conecta em cada servidor e mostra as ferramentas liberadas (e quais pedem código), as que estão no `permitir` mas o servidor não tem, e todas as outras que ele oferece. O `python doctor.py` mostra o mesmo quando `JARVIS_ENABLE_MCP=true`.

## Como falar

Peça do jeito normal: "quais issues abertas eu tenho no Jarvis-AI?", "lê a issue 4", "procura a página da reunião no Notion". Para o modelo, cada ferramenta aparece com o nome do serviço na frente (`github_list_issues`), então ela nunca se confunde com as do próprio Jarvis.

Durante a chamada, a placa do núcleo mostra "MCP-32 · GitHub · list_issues". O resultado vai para um painel do HUD, com uma linha por item quando ele é uma lista, e o Jarvis fala só o resumo.

"Quais integrações você tem?" chama o `mcp_status`, que diz quais servidores conectaram e com quais ferramentas.

## Ferramentas que escrevem

Criar issue, comentar, apagar página ou mandar mensagem seguem o esquema do email e da agenda: a ferramenta só prepara a ação, o painel mostra o que vai ser feito e o código, e nada acontece até você dizer "confirmar integração" e o código. "Cancela" desiste.

O Jarvis decide pelo nome da ferramenta. Porta, fechadura, portão, garagem, alarme e câmera, no nome ou nos argumentos, sempre pedem código, mesmo em `sem_confirmar` (veja [casa.md](casa.md#o-que-pede-código)). Nomes com `list`, `get`, `read`, `search`, `find` e parecidos são de leitura. Nomes com `create`, `update`, `delete`, `send`, `comment`, `merge`, `play` e parecidos são de escrita, e um nome que não diz nada também pede código. O `confirmar` e o `sem_confirmar` do `mcp.json` corrigem isso ferramenta por ferramenta.

## Casa inteligente

O Home Assistant entra como mais um servidor: token, `mcp.json` e o que pede código estão em [casa.md](casa.md).

## Quando um servidor não responde

Os servidores conectam em paralelo quando o link abre. O que não responder em `JARVIS_MCP_TIMEOUT` segundos, ou não subir, fica de fora sem derrubar o link e sem segurar os outros. Se você pedir algo dele, o Jarvis chama o `mcp_status` e diz que a integração está indisponível e por quê: token faltando no `.env`, nada em `permitir`, servidor fora do ar ou comando não encontrado.

Um servidor que cai no meio da conversa responde a cada pedido com "a integração está indisponível agora", e o resto continua normal.

## Poucas ferramentas

O Gemini Live erra mais quando tem ferramentas demais no contexto, e o Jarvis já tem perto de 80. Libere só o que você usa de verdade; duas ou três por serviço costumam bastar.

Servidores locais (`npx`) sobem junto com cada conversa, então o link pode demorar um pouco mais para abrir. Se incomodar, prefira o servidor HTTP do serviço quando existir.

Com as ferramentas sob demanda ligadas ([ferramentas-sob-demanda.md](ferramentas-sob-demanda.md)), cada servidor vira um grupo com o nome dele. Ele não conecta quando o link abre, e sim na primeira vez que o Jarvis pede o grupo ("Um instante." e a resposta). Até lá o `mcp_status` diz "ainda conectando".

As regras do que um servidor pode e não pode fazer estão em [seguranca.md](seguranca.md#integrações-mcp).

## Como testar

1. Crie um token do GitHub com acesso de leitura às issues, coloque em `GITHUB_MCP_TOKEN` e copie o `mcp.example.json` para `mcp.json`.
2. `python mcp_client.py`: o GitHub aparece conectado, com `list_issues`, `issue_read` e `search_issues` liberadas.
3. `python jarvis.py --rebuild`, conecte e confira o MCP-32 no painel Protocolos, com o GitHub e as ferramentas.
4. "Quais issues abertas eu tenho no Jarvis-AI?": a placa mostra "MCP-32 · GitHub · list_issues", o painel lista as issues e o Jarvis resume.
5. Ponha `create_issue` no `permitir`, reinicie e peça "cria uma issue chamada teste do MCP". O Jarvis fala o código e nada é criado até "confirmar integração" e o código. Teste também "cancela".
6. Tire o token do `.env` e peça as issues de novo: o Jarvis diz que a integração do GitHub está indisponível porque falta o token.
