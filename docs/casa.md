# Casa inteligente

O Jarvis controla a casa pelo servidor MCP do Home Assistant, dentro do protocolo MCP-32. Não tem ferramenta própria: o Home Assistant é mais uma entrada no `mcp.json`, com as travas de [integracoes.md](integracoes.md).

"Apaga a luz do escritório", "liga o ar da sala", "deixa a luz da sala em 40%", "a porta da frente está trancada?".

## No Home Assistant

1. Em Configurações, Dispositivos e serviços, adicione a integração Model Context Protocol Server. No controle, escolha Assist.
2. Em Configurações, Assistentes de voz, aba Expor, deixe só as entidades que o Jarvis pode ver e mexer. O que não estiver exposto não existe para ele.
3. Crie um usuário só para o Jarvis, sem ser administrador. Entre com ele, abra o perfil (o nome no canto de baixo), aba Segurança, e crie um token em Tokens de acesso de longa duração. O token aparece uma vez só: copie na hora.

## No Jarvis

No `.env`:

```env
JARVIS_ENABLE_MCP=true
HOME_ASSISTANT_TOKEN=o-token-de-longa-duracao
```

No `mcp.json` (a entrada já vem no `mcp.example.json`):

```json
{
  "home_assistant": {
    "url": "http://192.168.0.10:8123/api/mcp",
    "token_env": "HOME_ASSISTANT_TOKEN",
    "permitir": ["GetLiveContext", "HassTurnOn", "HassTurnOff", "HassLightSet", "HassSetVolume"],
    "sem_confirmar": ["HassTurnOn", "HassTurnOff", "HassLightSet", "HassSetVolume"]
  }
}
```

Troque o IP pelo do seu Home Assistant. O `http://` vale para um IP da rede de casa (`192.168.x.x`, `10.x.x.x`, `172.16.x.x` a `172.31.x.x`). Um nome como `homeassistant.local` precisa de `https://`, então use o IP ou o endereço `https://` do Nabu Casa. Versões antigas do Home Assistant usam `/mcp_server/sse` no lugar de `/api/mcp`.

Depois confira:

```bash
python mcp_client.py
```

Ele mostra o Home Assistant conectado, as ferramentas liberadas e todas as que o servidor oferece. Os nomes da lista acima são os do Assist do Home Assistant, mas mudam entre versões e dependem do que está exposto: confira com esse comando e acerte o `permitir`. Scripts expostos também viram ferramentas, com o nome do script.

## As ferramentas

| Ferramenta | O que faz | Exemplo |
| --- | --- | --- |
| `GetLiveContext` | Lê o estado de tudo que está exposto | "A porta da frente está trancada?" |
| `HassTurnOn` | Liga, abre ou tranca | "Liga o ar da sala" |
| `HassTurnOff` | Desliga, fecha ou destranca | "Apaga a luz do escritório" |
| `HassLightSet` | Brilho e cor da luz | "Deixa a luz da sala em 40%" |
| `HassSetVolume` | Volume de um aparelho de mídia | "Abaixa o som da sala para 20" |

Para o modelo elas aparecem com o serviço na frente: `home_assistant_HassTurnOff`. A placa do núcleo mostra "MCP-32 · Home Assistant · HassTurnOff".

## O que pede código

Acender luz, ligar o ar e mudar o volume rodam direto, porque estão em `sem_confirmar`. Sem essa lista, tudo que não é leitura pede código, como em qualquer integração.

Porta, fechadura, portão, garagem, alarme e câmera sempre pedem "confirmar integração" e o código, mesmo em `sem_confirmar`. O Jarvis olha o nome da ferramenta e o que ela recebe (o nome da entidade, a área, o tipo):

| Pede código | Roda direto |
| --- | --- |
| "Destranca a porta da frente" (`HassTurnOff`, porta da frente) | "Apaga a luz do escritório" |
| "Abre o portão da garagem" | "Liga o ar da sala" |
| "Desliga o alarme" | "Deixa a luz da sala em 40%" |
| "Desliga a câmera do quintal" | "A porta da frente está trancada?" (só lê) |
| Um script chamado `abrir_portao` | |

As palavras, em português e inglês: porta, portão, garagem, fechadura, tranca, trava, alarme, sirene, câmera, cofre, door, gate, garage, lock, alarm, arm, camera, siren. Acentos e maiúsculas não importam.

A regra erra para o lado seguro. "Liga a luz da garagem" pede código porque a área é a garagem. Se incomodar, renomeie a entidade (por exemplo "luz do depósito") ou aceite o código. Pedir o estado nunca pede código, mesmo falando de porta.

## Quando não funciona

| O que acontece | O que fazer |
| --- | --- |
| "falta HOME_ASSISTANT_TOKEN no .env" | Coloque o token no `.env` e reinicie |
| "url precisa ser https://" | Use o IP da rede de casa ou o `https://` do Nabu Casa |
| Conectou, mas não acha a luz | Exponha a entidade no Home Assistant (Assistentes de voz, Expor) |
| "no 'permitir', mas o servidor não tem" | O nome da ferramenta mudou na sua versão: copie o nome que o `python mcp_client.py` mostra |
| A resposta do estado vem cortada | O `GetLiveContext` traz todas as entidades expostas e o Jarvis corta em 6000 caracteres. Exponha menos coisas |

As regras de segurança estão em [seguranca.md](seguranca.md#casa-inteligente).
