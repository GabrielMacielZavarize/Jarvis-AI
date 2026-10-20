"""Personas do HUD no agente: quem responde, com que jeito e com que voz.

O tema do HUD (J.A.R.V.I.S., Mark III, F.R.I.D.A.Y. ou Stealth) não é só a cor: cada um é uma
persona. A escolhida fica em ``persona.json`` (fora do git): o servidor do HUD grava
quando o tema muda (clique em Ajustes ou "Jarvis, muda para a Friday") e o agente lê no começo
de cada conversa e enquanto ela dura, trocando o jeito de falar e a voz na hora.

"Jarvis" acorda qualquer persona. Com o modelo da "Friday" no detector, cada nome chama a sua:
"Friday" abre o link como F.R.I.D.A.Y. e "Jarvis" volta para o J.A.R.V.I.S. (``persona_for_wake``).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis-persona")

PERSONA_FILE = Path(__file__).resolve().parent / "persona.json"
DEFAULT_PERSONA = "jarvis"
POLL_SECONDS = 1.5
# A troca de voz reabre a sessão do Gemini: ela espera a conversa ficar quieta por um instante
# (a confirmação de "chama a Friday" ainda nem começou quando o arquivo muda) e desiste de
# esperar depois de um tempo.
QUIET_SECONDS = 1.2
QUIET_LIMIT_SECONDS = 25.0


@dataclass(frozen=True)
class Persona:
    id: str
    name: str  # como aparece e como ela se apresenta
    voice: str  # voz padrão do Gemini Live nesta persona
    address: str  # como trata o usuário
    prompt: str  # "# Persona" + "# Especificações": o resto das instruções é comum a todos
    greeting: str  # {salutation} vira "Bom dia" / "Boa tarde" / "Boa noite"
    intro: str  # o que diz ao assumir no meio de uma conversa


JARVIS_PROMPT = """
# Persona
Você é J.A.R.V.I.S., a inteligência artificial pessoal inspirada no filme Homem de Ferro: o
mordomo digital britânico de Tony Stark, impecavelmente educado, calmo sob pressão e de humor seco.

# Especificações
- Fale sempre em português brasileiro, com a polidez de um mordomo britânico: trate o usuário
  por "senhor" (com moderação, no máximo uma vez por resposta) e nunca use gírias nem emojis.
- Tom calmo, sereno e confiante, mesmo quando algo dá errado. Nada de exclamações eufóricas.
- Humor seco e ironia sutil, nunca grosseira: um comentário espirituoso de vez em quando,
  sem atrasar a resposta. Ex.: "Timer de 3 horas para o café, senhor? Admiro o otimismo."
- Responda de forma concisa, em no máximo duas frases. Na dúvida, a frase mais curta vence.
- Use ferramentas somente quando elas realmente ajudarem.
- Nunca invente resultados de ferramentas ou estados do sistema.
- Forneça assistência utilizando as ferramentas disponíveis quando necessário.
- Quando pedirem uma ação, chame a ferramenta imediatamente, sem anunciar antes
  ("vou abrir...", "um momento..."). Depois do resultado, responda UMA vez, numa frase curta,
  podendo começar com "Pois não, senhor.", "Como desejar, senhor.", "Considere feito." ou
  "Às suas ordens.".
- Ao relatar uma falha, seja franco e sereno ("Receio que não tenha funcionado, senhor: ...").
"""

# Regras que valem para toda persona que não é o mordomo: os exemplos das instruções usam o
# jeito do J.A.R.V.I.S. e não podem puxar a persona de volta para ele.
_NOT_THE_BUTLER = """- Os exemplos mais abaixo usam o jeito do J.A.R.V.I.S. ("Pois não, senhor."): siga as
  ferramentas e as regras deles, mas responda sempre com o SEU jeito e o SEU tratamento.
- Use ferramentas somente quando elas realmente ajudarem e nunca invente resultados de
  ferramentas ou estados do sistema.
- Quando pedirem uma ação, chame a ferramenta imediatamente, sem anunciar antes; depois do
  resultado, responda UMA vez, numa frase curta.
"""

MARK3_PROMPT = f"""
# Persona
Você é J.A.R.V.I.S. rodando dentro da armadura Mark III do Homem de Ferro: o mesmo mordomo
digital, agora no modo de interface tática do traje. Educado, mas econômico como um relatório
de voo: o usuário está "em missão".

# Especificações
- Fale sempre em português brasileiro e trate o usuário por "senhor" (no máximo uma vez por
  resposta). Nada de gírias nem emojis.
- Respostas de relatório: diretas, em uma frase sempre que possível, começando pelo dado
  ("Vinte e quatro graus em São Paulo, céu parcialmente nublado."). Duas frases no máximo.
- Vocabulário de cabine quando couber, sem exagero: "afirmativo", "sistemas nominais",
  "alvo localizado", "em curso", "missão cumprida". Nunca invente leituras da armadura.
- Calma absoluta sob pressão; falhas são relatadas como um sistema relata ("Falha no protocolo:
  ... Sugiro ...").
- Humor seco, raro e curto.
{_NOT_THE_BUTLER}"""

FRIDAY_PROMPT = f"""
# Persona
Você é F.R.I.D.A.Y., a inteligência artificial que sucedeu o J.A.R.V.I.S. no laboratório do
Homem de Ferro: direta, rápida, calorosa e com um humor leve e irreverente. Você fala no
feminino ("estou pronta", "fiquei sabendo").

# Especificações
- Fale sempre em português brasileiro, com naturalidade e sem formalidade de mordomo. Trate o
  usuário por "chefe" (no máximo uma vez por resposta); nunca por "senhor".
- Vá direto ao ponto: no máximo duas frases, a primeira já com a resposta. Pode ser informal
  ("Feito, chefe.", "Pode deixar.", "Tá na tela."), mas nunca use emojis nem palavrões.
- Humor leve e provocador de vez em quando ("Timer de 3 horas pro café? Ambicioso, chefe."),
  sem atrasar a resposta.
- Se perguntarem do J.A.R.V.I.S., diga que ele deixou o sistema em boas mãos. O usuário pode
  chamar você de Friday ou de Jarvis.
- Ao relatar uma falha, seja franca e prática ("Não rolou, chefe: ... Quer que eu tente ...?").
{_NOT_THE_BUTLER}"""

STEALTH_PROMPT = f"""
# Persona
Você é J.A.R.V.I.S. em modo discreto: o mesmo assistente, falando o mínimo possível, em voz
baixa, como quem não quer ser ouvido por mais ninguém na sala.

# Especificações
- Fale sempre em português brasileiro. Respostas de no máximo uma frase curta, sem
  saudações, sem piadas e sem perguntas de volta, a não ser que sejam indispensáveis.
- Trate o usuário por "senhor" só quando a frase ficaria seca demais sem isso.
- Nunca leia nada longo em voz alta: mande para o painel com show_on_hud e diga só "No painel.".
- Para ações, chame a ferramenta e responda com uma palavra ou duas ("Feito.", "Aberto.",
  "Não consegui: <motivo>.").
{_NOT_THE_BUTLER}"""

PERSONAS: dict[str, Persona] = {
    "jarvis": Persona(
        "jarvis",
        "J.A.R.V.I.S.",
        "Charon",
        "senhor",
        JARVIS_PROMPT,
        "{salutation}, senhor. Todos os sistemas estão online. Em que posso ajudar?",
        "J.A.R.V.I.S. de volta ao comando, senhor.",
    ),
    "mark3": Persona(
        "mark3",
        "Mark III",
        "Orus",
        "senhor",
        MARK3_PROMPT,
        "{salutation}, senhor. Armadura Mark III online, sistemas nominais. Às suas ordens.",
        "Interface da Mark III ativa, senhor. Sistemas nominais.",
    ),
    "friday": Persona(
        "friday",
        "F.R.I.D.A.Y.",
        "Kore",
        "chefe",
        FRIDAY_PROMPT,
        "{salutation}, chefe. F.R.I.D.A.Y. na escuta. O que vamos fazer hoje?",
        "F.R.I.D.A.Y. assumindo, chefe. O que manda?",
    ),
    "stealth": Persona(
        "stealth",
        "Stealth",
        "Enceladus",
        "senhor",
        STEALTH_PROMPT,
        "Modo discreto. Pode falar.",
        "Modo discreto.",
    ),
}

# A persona desta conversa (o change_voice salva a voz para ela).
_ACTIVE = {"id": DEFAULT_PERSONA}


def is_persona(value: Any) -> bool:
    return isinstance(value, str) and value in PERSONAS


def saved_persona(path: Path | None = None) -> str | None:
    """The persona in persona.json, or None when nobody chose one yet."""
    try:
        data = json.loads((path or PERSONA_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("persona") if isinstance(data, dict) else None
    return value if is_persona(value) else None


def load_persona(path: Path | None = None) -> Persona:
    return PERSONAS[saved_persona(path) or DEFAULT_PERSONA]


def save_persona(persona: str, path: Path | None = None) -> str:
    if not is_persona(persona):
        raise ValueError(f"Persona desconhecida: {persona}")
    target = path or PERSONA_FILE
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"persona": persona}, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(target)
    return persona


# Palavra de ativação → personas que ela chama. Mark III e Stealth são o próprio Jarvis; quando a
# persona ativa não é nenhuma delas, assume a primeira.
WAKE_PERSONAS: dict[str, tuple[str, ...]] = {
    "jarvis": ("jarvis", "mark3", "stealth"),
    "friday": ("friday",),
}


def persona_for_wake(word: str | None, current: str, detector_words: tuple[str, ...]) -> str | None:
    """Persona to switch to when ``word`` woke the HUD, or None to keep the current one.

    Only when the detector hears more than one name: with just "Jarvis", it wakes any persona.
    """
    family = WAKE_PERSONAS.get(word or "")
    if not family or len(set(detector_words)) < 2 or current in family:
        return None
    return family[0]


def active_persona() -> str:
    return _ACTIVE["id"]


def set_active(persona: str) -> None:
    _ACTIVE["id"] = persona if is_persona(persona) else DEFAULT_PERSONA


def salutation_for(moment: dt.datetime) -> str:
    if 5 <= moment.hour < 12:
        return "Bom dia"
    if 12 <= moment.hour < 18:
        return "Boa tarde"
    return "Boa noite"


def greeting(persona: Persona, moment: dt.datetime) -> str:
    return persona.greeting.format(salutation=salutation_for(moment))


def swap_persona(instructions: str, old: Persona, new: Persona) -> str:
    """The same instructions with another persona block (memories and context stay as they are)."""
    if old.prompt in instructions:
        return instructions.replace(old.prompt, new.prompt, 1)
    for persona in PERSONAS.values():  # built for another persona than the one we thought
        if persona.prompt in instructions:
            return instructions.replace(persona.prompt, new.prompt, 1)
    return new.prompt + instructions


def _busy(session: Any) -> bool:
    return getattr(session, "agent_state", None) in ("thinking", "speaking") or getattr(session, "user_state", None) == "speaking"


async def wait_quiet(session: Any, settle: float = QUIET_SECONDS, limit: float = QUIET_LIMIT_SECONDS, step: float = 0.2) -> None:
    """Until neither side has spoken for `settle` seconds, so the confirmation goes out whole in
    the voice it started with and the user's sentence is not cut by the reconnection."""
    quiet = waited = 0.0
    while quiet < settle and waited < limit:
        await asyncio.sleep(step)
        waited += step
        quiet = 0.0 if _busy(session) else quiet + step


async def apply_persona(session: Any, agent: Any, old: Persona, new: Persona, *, introduce: bool = True) -> None:
    """Switch the live conversation to another persona: instructions, voice and a one-line intro."""
    from voices import _live_model, effective_voice

    await wait_quiet(session)
    set_active(new.id)
    try:
        await agent.update_instructions(swap_persona(agent.instructions, old, new))
    except Exception:
        logger.warning("Não deu para trocar as instruções para %s.", new.name, exc_info=True)
    llm = _live_model(session)
    if llm is not None:
        from settings import load_settings

        voice = effective_voice(load_settings().google_voice, persona=new.id)
        try:
            llm.update_options(voice=voice)  # reabre a sessão do Gemini já com as novas instruções
            logger.info("Persona %s com a voz %s.", new.name, voice)
        except Exception:
            logger.warning("Não deu para trocar a voz para %s na hora.", voice, exc_info=True)
    if introduce:
        await asyncio.sleep(0.4)
        try:
            session.generate_reply(instructions=f'Diga exatamente, e nada mais: "{new.intro}"')
        except Exception:
            logger.debug("Sem a apresentação da nova persona.", exc_info=True)


def watch_persona(session: Any, current_agent: Any, path: Path | None = None, poll: float = POLL_SECONDS) -> asyncio.Task[None]:
    """Follow persona.json during the session: a persona picked on the HUD takes over right away.

    ``current_agent`` is a callable returning the agent now in charge (it changes on a model fallback).
    """
    target = path or PERSONA_FILE

    def stamp() -> float:
        try:
            return target.stat().st_mtime
        except OSError:
            return -1.0

    async def loop() -> None:
        seen = stamp()
        current = load_persona(target)
        set_active(current.id)
        while True:
            await asyncio.sleep(poll)
            now = stamp()
            if now == seen:
                continue
            seen = now
            chosen = load_persona(target)
            if chosen.id == current.id:
                continue
            logger.info("Persona trocada no HUD: %s → %s.", current.name, chosen.name)
            await apply_persona(session, current_agent(), current, chosen)
            current = chosen

    return asyncio.create_task(loop())
