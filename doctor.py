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
        print(f"Modelo Gemini: {settings.google_model}")
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

    if settings.calendar_enabled:
        from calendar_tools import CREDENTIALS_FILE, is_connected

        reminder = settings.calendar_reminder_minutes
        print(
            "Google Agenda (AGD-27): ativado, "
            + ("conectado" if is_connected() else "SEM LOGIN")
            + (f", aviso {reminder} min antes das reuniões" if reminder else ", sem aviso de reuniões")
        )
        if not is_connected():
            step = "python calendar_tools.py --login" if CREDENTIALS_FILE.exists() else "veja 'Google Agenda' no README"
            print(f"Aviso: conecte a agenda com: {step}")
    else:
        print("Google Agenda (AGD-27): desativado")

    print(
        "Palavra de ativação (WAK-22): "
        f"{'ativada' if settings.wake_word_enabled else 'desativada'}"
    )
    if settings.wake_word_enabled:
        silence = f"{settings.wake_silence_seconds} s" if settings.wake_silence_seconds else "nunca"
        print(f"Limiar: {settings.wake_threshold:.2f} · encerra o link após silêncio de: {silence}")
        missing = [name for name in ("openwakeword", "sounddevice") if importlib.util.find_spec(name) is None]
        if missing:
            problems.append(f"Palavra de ativação ligada, mas falta instalar: pip install {' '.join(missing)}")
            print(f"Aviso: {problems[-1]}")
        else:
            print("Calibre a sensibilidade com: python wake_word.py --test")

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
