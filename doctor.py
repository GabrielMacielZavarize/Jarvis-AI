from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

from backends import build_backend_components
from settings import SettingsError, load_settings


def _print_section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def main() -> int:
    print("Jarvis Doctor")
    print("Validação local e não destrutiva do projeto.")

    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"\nERRO: {exc}")
        return 1

    problems = [
        *settings.backend_validation_errors(),
        *settings.email_validation_errors(),
    ]
    warnings = settings.livekit_validation_errors()

    _print_section("Configuração")
    print(f"Backend selecionado: {settings.backend}")
    if settings.backend == "gemini-realtime":
        from model_pool import pool_for

        print(f"Modelo Gemini: {settings.google_model}")
        if settings.google_fallback_models:
            rotation = "rodízio a cada link" if settings.model_rotation == "rotate" else "reservas só quando o principal falha"
            print(f"Modelos ({rotation}):")
            for line in pool_for(settings).describe():
                print(f"- {line}")
        else:
            print("Modelos de reserva: nenhum (GOOGLE_FALLBACK_MODELS vazio)")
        if "thinking" in settings.google_model:
            print("Aviso: modelos 'extended-thinking' pensam antes de falar e respondem mais devagar.")
        end = f"{settings.end_of_speech_ms} ms de silêncio" if settings.end_of_speech_ms else "padrão do Google"
        print(f"Fim da sua fala (JARVIS_END_OF_SPEECH_MS): {end}")
    silence = f"após {settings.wake_silence_seconds} s de silêncio" if settings.wake_silence_seconds else "nunca"
    print(f"Link fecha sozinho (JARVIS_WAKE_SILENCE_SECONDS): {silence}")
    print(
        "Ferramenta de email: "
        f"{'ativada' if settings.email_tool_enabled else 'desativada'}"
    )
    if settings.email_tool_enabled:
        allowed = ", ".join(settings.effective_allowed_emails) or "nenhum"
        print(f"Destinatários permitidos: {allowed}")
    print(
        "Instalação de apps (winget): "
        f"{'ativada' if settings.app_install_enabled else 'desativada'}"
    )
    print(
        "Gestos das mãos (webcam): "
        f"{'ativados' if settings.gestures_enabled else 'desativados'}"
    )
    if settings.app_install_enabled and not shutil.which("winget"):
        print("Aviso: winget não encontrado; instale o 'App Installer' pela Microsoft Store.")
    print(
        "Mouse e teclado (MOU-20): "
        f"{'ativado, visão com ' + settings.computer_use_model if settings.computer_use_enabled else 'desativado'}"
    )

    if not settings.memory_enabled:
        print("Memória (MEM-23): desativada")
    elif not settings.memory_embeddings:
        print("Memória (MEM-23): busca só por palavras (JARVIS_MEMORY_EMBEDDINGS=false)")
    elif not settings.google_api_key:
        print("Memória (MEM-23): busca só por palavras; a busca pelo sentido precisa da GOOGLE_API_KEY")
    else:
        print(
            f"Memória (MEM-23): busca pelo sentido com {settings.memory_embedding_model}, "
            f"limiar {settings.memory_min_similarity:.2f}"
        )

    if settings.calendar_enabled:
        from calendar_tools import CREDENTIALS_FILE, is_connected

        reminder = settings.calendar_reminder_minutes
        print(
            "Google Agenda (AGD-27): ativado, "
            + ("conectado" if is_connected() else "SEM LOGIN")
            + (f", aviso {reminder} min antes das reuniões" if reminder else ", sem aviso de reuniões")
        )
        if not is_connected():
            step = "python calendar_tools.py --login" if CREDENTIALS_FILE.exists() else "veja docs/agenda.md"
            print(f"Aviso: conecte a agenda com: {step}")
    else:
        print("Google Agenda (AGD-27): desativado")

    print(
        "Palavra de ativação (WAK-22): "
        f"{'ativada' if settings.wake_word_enabled else 'desativada'}"
    )
    if settings.wake_word_enabled:
        from wake_word import WORD_MODELS, available_words, word_label

        print("Palavras e limiares: " + ", ".join(f"{word_label(word)} {limit:.2f}" for word, limit in settings.wake_thresholds))
        for word in available_words(settings.wake_words)[1]:
            print(
                f"Aviso: modelo de “{word_label(word)}” não encontrado em {WORD_MODELS[word]}; "
                "o detector segue só com as outras palavras. Veja docs/voz.md."
            )
        missing = [name for name in ("openwakeword", "sounddevice") if importlib.util.find_spec(name) is None]
        if missing:
            problems.append(f"Palavra de ativação ligada, mas falta instalar: pip install {' '.join(missing)}")
            print(f"Aviso: {problems[-1]}")
        else:
            print("Calibre a sensibilidade com: python wake_word.py --test")

    if settings.mcp_enabled:
        import asyncio

        from mcp_client import check_servers

        _print_section("Integrações MCP (MCP-32)")
        for line in asyncio.run(check_servers(settings)):
            print(line)

    _print_section("Backend")
    if problems:
        print("Falhas encontradas:")
        for item in problems:
            print(f"- {item}")
    else:
        try:
            components = build_backend_components(settings)
            print(f"Backend carregado com sucesso: {components.backend}")
            print(
                "Modo: "
                f"{'realtime' if components.is_realtime else 'pipeline compatível'}"
            )
            llm_name = type(components.llm).__name__ if components.llm else "nenhum"
            stt_name = type(components.stt).__name__ if components.stt else "nenhum"
            tts_name = type(components.tts).__name__ if components.tts else "nenhum"
            print(f"LLM: {llm_name}")
            print(f"STT: {stt_name}")
            print(f"TTS: {tts_name}")
        except Exception as exc:
            problems.append(f"Falha ao instanciar o backend localmente: {exc}")
            print("Falhas encontradas:")
            print(f"- {problems[-1]}")

    _print_section("LiveKit")
    if warnings:
        print("Avisos:")
        for item in warnings:
            print(f"- {item}")
        print("Sem essas variáveis, os comandos dev/start/connect não vão subir.")
    else:
        print("LIVEKIT_URL, LIVEKIT_API_KEY e LIVEKIT_API_SECRET estão configuradas.")

    _print_section("HUD holográfico")
    web_dir = Path(__file__).resolve().parent / "web"
    if (web_dir / "dist" / "index.html").exists():
        print("Interface compilada em web/dist.")
    elif shutil.which("npm"):
        print("Interface ainda não compilada; `python jarvis.py` compila na primeira execução.")
    else:
        print("Node.js/npm não encontrado: instale o Node 20+ para compilar a interface.")

    _print_section("Próximos passos")
    if problems:
        print("Corrija os problemas acima e rode `python3 doctor.py` novamente.")
        return 1

    print("HUD + agente: python3 jarvis.py")
    print("Console: python3 agent.py console")
    print("Checagem rápida: python3 agent.py --help")
    if warnings:
        print("Dev/Start/Connect: disponíveis após configurar as variáveis LIVEKIT_*.")
    else:
        print("Dev: python3 agent.py dev")
        print("Start: python3 agent.py start")
        print("Connect: python3 agent.py connect --room <nome-da-sala>")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
