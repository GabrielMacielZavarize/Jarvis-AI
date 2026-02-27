# 🤖 Jarvis - Assistente Pessoal com IA

Fala dev tudo certo? A um tempo que queria fazer o JARVIS afinal sou um grande fã dos filmes da Marvel, e decidi tirar um tempinho para fazer isso, encontrei um cara na gringa que utilizou o livekit para fazer um assistente de voz com o codinome Jarvis (Ele criou a Friday junto). 

O vídeo é um pouco antigo atualmente neste commit faz 8 meses que ele fez, e bastante coisas mudaram, passei por alguns erros no qual deixei documentado, e utilizei muito a documentação do livekit. 

Ao final deste README deixo as referências para o vídeo original e a documentação do livekit.

Espero que gostem, e é claro esse projeto é só a pontinha do iceberg, utilize a documentação do livekit para ver o quão longe você vai apartir daqui.

## ✨ Funcionalidades

- 🗣️ **Conversa por voz** — Interação em tempo real com voz natural (Google Gemini Live API)
- 🔍 **Pesquisa na web** — Busca informações na internet via DuckDuckGo
- 🌤️ **Clima** — Consulta o clima atual de qualquer cidade (via Open-Meteo)
- 📧 **Envio de emails** — Envia emails pelo Gmail
- 🔇 **Cancelamento de ruído** — Filtragem de ruído de fundo automática

## 📋 Pré-requisitos

- Python 3.10+
- Conta no [LiveKit Cloud](https://cloud.livekit.io/) (gratuito)
- Chave da [Google AI API](https://aistudio.google.com/apikey) (Gemini)
- Biblioteca PortAudio instalada no sistema (para modo console)
- (Opcional) Conta Gmail com [App Password](https://myaccount.google.com/apppasswords) para envio de emails

## 🚀 Instalação

### 1. Clone o repositório

```bash
git clone https://github.com/seu-usuario/jarvis.git
cd jarvis
```

### 2. Crie e ative o ambiente virtual

```bash
python -m venv venv

source venv/bin/activate  # Linux/Mac

venv\Scripts\activate     # Windows
```

### 3. Instale as dependências

```bash
npm install -r requirements.txt
```

### 4. Instale o PortAudio (necessário para modo console)

```bash
# Ubuntu/Debian
sudo apt-get install -y libportaudio2 portaudio19-dev

# Fedora
sudo dnf install portaudio portaudio-devel

# macOS
brew install portaudio
```

### 5. Configure as variáveis de ambiente

Copie o arquivo de exemplo e preencha com suas credenciais:

```bash
cp .env.example .env
```

Edite o `.env` com suas chaves:

```env
LIVEKIT_URL=wss://seu-projeto.livekit.cloud
LIVEKIT_API_KEY=sua-api-key
LIVEKIT_API_SECRET=seu-api-secret
GOOGLE_API_KEY=sua-google-api-key
```

### 6. Baixe os modelos necessários

```bash
python agent.py download-files
```

## ▶️ Como usar

### Modo Console (direto no terminal)

```bash
python agent.py console
```

Fale pelo microfone e ouça a resposta pelo alto-falante do computador.

### Modo Dev (para usar com Playground/câmera)

```bash
python agent.py dev
```

Depois acesse o Playground pelo [LiveKit Cloud](https://cloud.livekit.io/) → seu projeto → **Sandbox** → **Web Voice Agent**.


## 🎙️ Vozes Disponíveis

Você pode alterar a voz do Jarvis editando o parâmetro `voice` no arquivo `agent.py`:

```python
llm=google.realtime.RealtimeModel(
    voice="Charon",  # ← Altere aqui
    temperature=0.8,
),
```

| Voz      | Gênero       | Descrição                                         |
| -------- | ------------ | ------------------------------------------------- |
| `Puck`   | Masculino | Voz masculina clara e versátil (padrão do Gemini) |
| `Charon` | Masculino | Voz masculina grave e profunda (atual)       |
| `Fenrir` | Masculino | Voz masculina firme e autoritária                 |
| `Orus`   | Masculino | Voz masculina calma e serena                      |
| `Aoede`  | Feminino  | Voz feminina suave e melodiosa                    |
| `Kore`   | Feminino  | Voz feminina expressiva e dinâmica                |
| `Leda`   | Feminino  | Voz feminina elegante e refinada                  |

## ⚙️ Configuração do Gmail (opcional)

Para usar a ferramenta de envio de emails:

1. Ative a [verificação em duas etapas](https://myaccount.google.com/security) na sua conta Google
2. Gere uma [App Password](https://myaccount.google.com/apppasswords)
3. Adicione no `.env` (com aspas se tiver espaços):
   ```env
   GMAIL_USER=seu-email@gmail.com
   GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
   ```

## 📚 Referências

- [Tutorial em vídeo](https://youtu.be/An4NwL8QSQ4)
- [Documentação LiveKit Agents](https://docs.livekit.io/agents/)
- [Google Gemini Live API](https://ai.google.dev/gemini-api/docs/live)
- [Repositório original](https://github.com/ruxakK/friday_jarvis)
