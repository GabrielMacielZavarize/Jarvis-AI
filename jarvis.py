"""Inicializador do Jarvis: sobe o agente de voz e o HUD holográfico juntos.

Uso:
    python jarvis.py                 # agente (modo dev) + HUD em http://127.0.0.1:8000
    python jarvis.py --no-agent      # apenas o HUD (útil para o modo demonstração)
    python jarvis.py --gestures      # liga também o controle de janelas por gestos (webcam)
    python jarvis.py --port 8080 --no-browser

Com JARVIS_WAKE_WORD=true também sobe o detector local da palavra "Jarvis" (wake_word.py).
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from settings import SettingsError, load_settings

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"


def _print_banner() -> None:
    print(
        "\n"
        "      ╔═══════════════════════════════════════════╗\n"
        "      ║   J . A . R . V . I . S .   //   v2.0     ║\n"
        "      ║   Just A Rather Very Intelligent System   ║\n"
        "      ╚═══════════════════════════════════════════╝\n"
    )


def _ensure_web_build(force: bool) -> bool:
    if (WEB_DIR / "dist" / "index.html").exists() and not force:
        return True

    npm = shutil.which("npm")
    if npm is None:
        print("[HUD] Node.js/npm não encontrado. Instale o Node 20+ para compilar a interface.")
        return False

    print("[HUD] Compilando a interface web (primeira execução)...")
    if not (WEB_DIR / "node_modules").exists():
        subprocess.run([npm, "install"], cwd=WEB_DIR, check=True)
    subprocess.run([npm, "run", "build"], cwd=WEB_DIR, check=True)
    return True


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def _local_url(host: str, port: int) -> str:
    """Endereço do servidor do HUD visto deste computador (0.0.0.0 escuta, mas não é destino)."""
    if host in ("", "0.0.0.0", "::"):
        host = "127.0.0.1"
    return f"http://{f'[{host}]' if ':' in host else host}:{port}"


def _start_agent(mode: str, hud_url: str) -> subprocess.Popen[bytes] | None:
    try:
        settings = load_settings()
        settings.validate_for_command(mode)
    except SettingsError as exc:
        print(f"[AGENTE] Não foi possível iniciar o agente:\n{exc}")
        print("[AGENTE] O HUD vai subir mesmo assim (modo demonstração disponível).")
        print("[AGENTE] Rode `python doctor.py` para um diagnóstico completo.\n")
        return None

    print(f"[AGENTE] Iniciando worker LiveKit ({mode}) com backend {settings.backend}...")
    # O worker é outro processo: pede a webcam (dona: o servidor do HUD) por HTTP nesse endereço.
    env = {**os.environ, "JARVIS_HUD_URL": hud_url}
    return subprocess.Popen([sys.executable, str(ROOT / "agent.py"), mode], cwd=ROOT, env=env)


def _start_wake_word(url: str) -> subprocess.Popen[bytes] | None:
    """Local detector of "Jarvis"; must start before the server is imported (it reads the secret)."""
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"[ATIVAÇÃO] Palavra de ativação desligada: {exc}")
        return None
    if not settings.wake_word_enabled:
        return None

    from wake_hub import SECRET_ENV

    os.environ[SECRET_ENV] = secrets.token_urlsafe(24)
    print("[ATIVAÇÃO] Iniciando o detector local da palavra “Jarvis” (o áudio não sai do PC)...")
    return subprocess.Popen([sys.executable, str(ROOT / "wake_word.py"), "--server", url], cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inicia o Jarvis com o HUD holográfico.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-agent", action="store_true", help="Não inicia o worker do agente.")
    parser.add_argument("--no-browser", action="store_true", help="Não abre o navegador.")
    parser.add_argument("--rebuild", action="store_true", help="Recompila a interface web.")
    parser.add_argument(
        "--gestures",
        action="store_true",
        help="Liga o controle de janelas por gestos das mãos (webcam) junto com o Jarvis.",
    )
    parser.add_argument(
        "--agent-mode",
        choices=("dev", "start"),
        default="dev",
        help="Modo do worker: dev (hot reload) ou start (produção).",
    )
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    _print_banner()
    if not _port_is_free(args.host, args.port):
        print(
            f"[HUD] A porta {args.port} já está em uso — provavelmente outro Jarvis ou servidor "
            f"ainda está aberto.\n[HUD] Feche-o ou escolha outra porta: python jarvis.py --port {args.port + 1}"
        )
        return 1
    if not _ensure_web_build(args.rebuild):
        return 1

    if args.gestures:
        # O agente herda estas variáveis: a ferramenta gesture_control fica disponível e os
        # gestos ligam junto com a sessão de voz.
        os.environ["JARVIS_ENABLE_GESTURES"] = "true"
        os.environ["JARVIS_GESTURES_AUTOSTART"] = "true"
    url = _local_url(args.host, args.port)
    # O agente pede a webcam e a presença ao servidor por aqui; o servidor abre o HUD por aqui.
    os.environ["JARVIS_HUD_URL"] = url
    agent_process = None if args.no_agent else _start_agent(args.agent_mode, url)
    gestures_here = args.gestures and agent_process is None
    if gestures_here:
        # Sem agente de voz, os gestos rodam aqui mesmo, só com o overlay.
        from gestures import SERVICE

        print(f"[GESTOS] {SERVICE.start()}")

    wake_process = _start_wake_word(url)
    print(f"[HUD] Interface disponível em {url}")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()

    from server import app, serve

    try:
        serve(app, host=args.host, port=args.port, log_level="warning")
    except KeyboardInterrupt:
        pass
    finally:
        if gestures_here:
            from gestures import SERVICE

            print(f"[GESTOS] {SERVICE.stop()}")
        if wake_process is not None:
            _stop_wake_word(wake_process)
        if agent_process is not None:
            _stop_agent(agent_process)

    return 0


def _stop_wake_word(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _stop_agent(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return

    print("\n[AGENTE] Encerrando worker...")
    process.terminate()
    try:
        process.wait(timeout=8)
        return
    except subprocess.TimeoutExpired:
        pass

    # O worker em modo dev cria subprocessos; no Windows terminate() não os alcança.
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        process.kill()
    process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
