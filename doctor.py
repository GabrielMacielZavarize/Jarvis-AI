from __future__ import annotations

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

    _print_section("Próximos passos")
    if problems:
        print("Corrija os problemas acima e rode `python3 doctor.py` novamente.")
        return 1

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
