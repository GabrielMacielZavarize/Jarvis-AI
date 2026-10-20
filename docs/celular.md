# Celular na rede de casa

Protocolo LAN-26. Você fala com o Jarvis pelo celular, no Wi-Fi de casa, com o link de voz, os painéis e o Jarvis mexendo no PC como sempre.

```bash
python jarvis.py --lan           # ou JARVIS_LAN=true no .env
```

O PC continua em `http://127.0.0.1:8000`. O celular abre `https://<ip-do-pc>:8000`, e o terminal mostra o endereço: `[LAN] Celular: https://192.168.0.12:8000`.

Na primeira vez o Windows pergunta se o Python pode usar a rede. Libere só em Redes privadas.

O HTTPS é obrigatório porque o navegador só libera o microfone em página segura. Na primeira execução o Jarvis cria uma autoridade certificadora local em `.jarvis-tls/` (só no seu PC, fora do git) e um certificado para os IPs do PC. Se o IP mudar, o certificado é refeito na próxima execução com a mesma autoridade, e o celular continua confiando.

## Pareando o celular

1. No HUD do PC, o painel CELULAR (coluna da esquerda, só aparece com `--lan`) mostra o endereço. Toque em Parear celular: aparecem um código de 6 dígitos e um QR, válidos por 5 minutos.
2. No celular, leia o QR com a câmera, ou abra o endereço e digite o código. Dê um nome ao aparelho ("Pixel do Gabriel") e toque em Parear.
3. O celular abre o HUD completo. Toque no núcleo para falar.

Para tirar um aparelho, use Revogar no mesmo painel. Ele perde o acesso na hora, inclusive o feed da câmera que estiver aberto, e em até 15 s volta para a tela de pareamento, o que também encerra o link de voz.

## Tirando o aviso de certificado

Sem isso o navegador mostra "Sua conexão não é particular" a cada visita. Dá para tocar em Avançado > Continuar e o microfone funciona, mas o PWA não instala direito. O melhor é instalar a autoridade do Jarvis no celular uma vez.

Ela só vale para IPs privados (`192.168.*`, `10.*` e de `172.16.*` a `172.31.*`) e nomes `.local`. Mesmo que alguém copiasse a chave, ela não serviria para se passar por outros sites.

No Android (Chrome), abra `https://<ip-do-pc>:8000/api/lan/ca.crt` (aceite o aviso dessa vez) ou toque no link da tela de pareamento. Depois vá em Configurações > Segurança e privacidade > Mais configurações de segurança > Criptografia e credenciais > Instalar um certificado > Certificado de CA, confirme "Instalar mesmo assim" e escolha o `jarvis-ca.crt` em Downloads. O caminho muda um pouco de fabricante para fabricante; se não achar, procure "certificado de CA" na busca das Configurações. Feche e abra o Chrome.

No iPhone (Safari), abra o mesmo endereço e toque em Permitir para baixar o perfil. Vá em Ajustes > Geral > VPN e Gerenciamento de Dispositivos > Jarvis CA local > Instalar. Depois ative em Ajustes > Geral > Sobre > Ajustes de Confiança de Certificados > Jarvis CA local. Sem esse último passo o iPhone continua desconfiando.

Para remover depois: no Android, em Credenciais do usuário; no iPhone, apagando o perfil em VPN e Gerenciamento de Dispositivos. Apagar a pasta `.jarvis-tls/` gera uma autoridade nova, e aí é preciso instalar de novo.

## Instalando como app (PWA)

No Android, no Chrome, menu e depois Instalar app (ou Adicionar à tela inicial).

No iPhone, no Safari, Compartilhar e depois Adicionar à Tela de Início. O app instalado tem armazenamento próprio no iPhone, então pareie de novo dentro do app (gere outro código no PC).

## Como fica no celular

O núcleo vira o botão de falar, grande no centro. O dock com Inicializar e Encerrar link e o microfone fica preso embaixo, e os painéis vêm empilhados abaixo do núcleo.

A cena 3D roda com menos pixels e só com o brilho (sem aberração, ruído e vinheta) para não esquentar o celular.

O áudio entra e sai pelo celular, mas o Jarvis continua agindo no PC: abre apps, move janelas, usa a webcam do notebook e o resto.

Dizer "Jarvis" perto do PC conecta só uma aba do PC, nunca o celular, e o microfone escolhido no celular não muda o microfone do detector.

As regras de acesso (o que responde sem pareamento, tokens, revogação) estão em [seguranca.md](seguranca.md#celular-na-rede).

## Como testar

1. `python jarvis.py --lan` e libere o Python em Redes privadas no aviso do Windows. Anote o endereço `[LAN] Celular: ...`.
2. Com o celular no mesmo Wi-Fi, abra o endereço sem parear: deve aparecer só a tela "Parear este aparelho". Tente `https://<ip>:8000/api/status` e `.../api/camera/snapshot` no navegador do celular: os dois devem responder `401`.
3. No PC, painel CELULAR, Parear celular. Leia o QR com a câmera do celular: ele deve parear sozinho e abrir o HUD, e o aparelho aparece na lista do PC.
4. Instale a CA (Android ou iPhone, acima) e reabra a página: o aviso de certificado some.
5. Toque no núcleo, permita o microfone e peça "Jarvis, abre o bloco de notas" e "que horas são?". O Jarvis responde pelo alto-falante do celular e o app abre no PC.
6. Peça "mostra a câmera": o feed da webcam do notebook aparece no celular, e o aviso CÂMERA ATIVA aparece nos dois.
7. Com o feed aberto, revogue o celular no PC: o feed congela na hora e, em até 15 s, o celular volta para a tela de pareamento e o link de voz cai.
8. Erre o código cinco vezes no celular: o código do PC some e é preciso gerar outro.
9. Instale o PWA, abra pelo ícone e confira que abre em tela cheia. No iPhone, pareie de novo dentro do app.
10. Com o PWA aberto, feche o Jarvis no PC e recarregue: deve aparecer o aviso "O PC não respondeu" (Android, com a CA instalada).
11. Diga "Jarvis" perto do PC com o HUD aberto no celular e no PC: só a aba do PC conecta.
