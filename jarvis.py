"""Inicializador do Jarvis: sobe o agente de voz e o HUD holográfico juntos.

Uso:
    python jarvis.py                 # agente (modo dev) + HUD em http://127.0.0.1:8000
    python jarvis.py --no-agent      # apenas o HUD (útil para o modo demonstração)
    python jarvis.py --port 8080 --no-browser
"""

from __future__ import annotations

import argparse
import os
import shutil
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


def _start_agent(mode: str) -> subprocess.Popen[bytes] | None:
    try:
        settings = load_settings()
        settings.validate_for_command(mode)
    except SettingsError as exc:
        print(f"[AGENTE] Não foi possível iniciar o agente:\n{exc}")
        print("[AGENTE] O HUD vai subir mesmo assim (modo demonstração disponível).")
        print("[AGENTE] Rode `python doctor.py` para um diagnóstico completo.\n")
        return None

    print(f"[AGENTE] Iniciando worker LiveKit ({mode}) com backend {settings.backend}...")
    return subprocess.Popen([sys.executable, str(ROOT / "agent.py"), mode], cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inicia o Jarvis com o HUD holográfico.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-agent", action="store_true", help="Não inicia o worker do agente.")
    parser.add_argument("--no-browser", action="store_true", help="Não abre o navegador.")
    parser.add_argument("--rebuild", action="store_true", help="Recompila a interface web.")
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
    if not _ensure_web_build(args.rebuild):
        return 1

    agent_process = None if args.no_agent else _start_agent(args.agent_mode)

    url = f"http://{args.host}:{args.port}"
    print(f"[HUD] Interface disponível em {url}")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()

    import uvicorn

    from server import app

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    except KeyboardInterrupt:
        pass
    finally:
        if agent_process is not None:
            _stop_agent(agent_process)

    return 0


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
