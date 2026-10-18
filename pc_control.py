"""Controle do computador por um conjunto fechado de ações seguras.

O Jarvis lê conteúdo da internet (pesquisas, notícias), e um texto malicioso pode
tentar dar ordens a ele. Por isso este módulo NÃO executa comandos arbitrários:
só existem ações visíveis e reversíveis — abrir/fechar apps e sites, mídia, volume,
abas do navegador, pastas, captura de tela e bloqueio de tela. Desinstaladores são
ignorados, processos do sistema e o próprio Jarvis são protegidos, e nenhum arquivo
ou credencial é lido. Cada ação fica registrada no log e no HUD.

O único programa lançado com argumentos é o navegador padrão (um executável de navegador
conhecido), com --new-window e uma URL http(s) já validada. Depois de abrir, fechar ou mover
algo, o resultado relata o que o Windows mostra de fato (janela visível, processo encerrado,
tela onde a janela ficou), nunca só o que foi pedido.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import difflib
import json
import logging
import os
import re
import subprocess
import sys
import time
import unicodedata
import webbrowser
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterator, Literal
from urllib.parse import quote, quote_plus, urlparse

import psutil
import requests
from livekit.agents import RunContext, function_tool

import win_desktop
from hud import net_activity, send_screenshot, show_card, tool_status
from vision import push_image_to_model

logger = logging.getLogger("jarvis-pc")

IS_WINDOWS = sys.platform == "win32"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HUD_TITLE = "J.A.R.V.I.S."
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)

# Atalhos do Menu Iniciar que nunca devem ser abertos (desinstalar/instalar/reparar).
BLOCKED_APP_WORDS = (
    "uninstall",
    "uninst",
    "desinstal",
    "remover",
    "remove",
    "setup",
    "instalador",
    "installer",
    "repair",
    "reparar",
)

BUILTIN_APPS = {
    "calculadora": "calc",
    "calculator": "calc",
    "bloco de notas": "notepad",
    "notepad": "notepad",
    "explorador de arquivos": "explorer",
    "explorer": "explorer",
    "arquivos": "explorer",
    "configuracoes": "ms-settings:",
    "configuracao": "ms-settings:",
    "settings": "ms-settings:",
    "gerenciador de tarefas": "taskmgr",
    "task manager": "taskmgr",
    "paint": "mspaint",
    "terminal": "wt",
}

# Apelidos falados -> nome no Menu Iniciar.
APP_NAME_ALIASES = {
    "vs code": "visual studio code",
    "vscode": "visual studio code",
    "zap": "whatsapp",
    "zapzap": "whatsapp",
    "navegador": "google chrome",
    "chrome": "google chrome",
    "edge": "microsoft edge",
    "loja": "microsoft store",
    "claudio": "claude",
    "cloud": "claude",
    "clode": "claude",
    "cloude": "claude",
    "php storm": "phpstorm",
    "configuracao": "configuracoes",
}

PROCESS_ALIASES = {
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "firefox": ["firefox.exe"],
    "brave": ["brave.exe"],
    "opera": ["opera.exe"],
    "spotify": ["spotify.exe"],
    "discord": ["discord.exe"],
    "vscode": ["code.exe"],
    "vs code": ["code.exe"],
    "visual studio code": ["code.exe"],
    "word": ["winword.exe"],
    "excel": ["excel.exe"],
    "powerpoint": ["powerpnt.exe"],
    "outlook": ["outlook.exe", "olk.exe"],
    "teams": ["ms-teams.exe", "teams.exe"],
    "whatsapp": ["whatsapp.exe", "whatsapp.root.exe"],
    "telegram": ["telegram.exe"],
    "steam": ["steam.exe"],
    "bloco de notas": ["notepad.exe"],
    "notepad": ["notepad.exe"],
    "calculadora": ["calculatorapp.exe", "calculator.exe"],
    "paint": ["mspaint.exe"],
    "obs": ["obs64.exe"],
    "vlc": ["vlc.exe"],
    "zoom": ["zoom.exe"],
}

BROWSER_PROCESSES = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe"}
DEFAULT_BROWSER_KEYS = (
    r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoiceLatest\ProgId",
    r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
)
EDGE_APP_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"

# Esperas depois de abrir/fechar algo: o Windows leva um tempo para mostrar ou encerrar janelas.
POLL_SECONDS = 0.3
SITE_WINDOW_SECONDS = 6.0
APP_WINDOW_SECONDS = 8.0
APP_REUSE_AFTER_SECONDS = 2.0  # sem janela nova até aqui, vale a que já estava aberta
APP_RELAUNCH_AFTER_SECONDS = 4.0
CLOSE_WAIT_SECONDS = 5.0
FIND_WINDOW_SECONDS = 2.0
# Títulos provisórios de uma janela de navegador que ainda está carregando.
PLACEHOLDER_TITLES = ("nova guia", "new tab", "about:blank", "carregando", "loading", "sem titulo", "untitled")
MAX_SAVED_POSITIONS = 10
MAX_REMEMBERED_WINDOWS = 30

# Processos do sistema que fechar derrubaria o Windows, a segurança ou o próprio Jarvis.
PROTECTED_PROCESSES = {
    "system",
    "registry",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "dwm.exe",
    "explorer.exe",
    "fontdrvhost.exe",
    "sihost.exe",
    "taskhostw.exe",
    "ctfmon.exe",
    "runtimebroker.exe",
    "audiodg.exe",
    "spoolsv.exe",
    "lockapp.exe",
    "msmpeng.exe",
    "securityhealthservice.exe",
    "securityhealthsystray.exe",
    "startmenuexperiencehost.exe",
    "shellexperiencehost.exe",
    "searchhost.exe",
    "textinputhost.exe",
    "conhost.exe",
    "python.exe",
    "pythonw.exe",
    "py.exe",
}

STREAMING_SERVICES: dict[str, tuple[str, str, str | None]] = {
    # chave: (nome, página inicial, modelo de busca com {q})
    "youtube": ("YouTube", "https://www.youtube.com", "https://www.youtube.com/results?search_query={q}"),
    "netflix": ("Netflix", "https://www.netflix.com/browse", "https://www.netflix.com/search?q={q}"),
    "prime video": (
        "Prime Video",
        "https://www.primevideo.com",
        "https://www.primevideo.com/search/ref=atv_nb_sug?ie=UTF8&phrase={q}",
    ),
    "spotify": ("Spotify", "https://open.spotify.com", "https://open.spotify.com/search/{path}"),
    "twitch": ("Twitch", "https://www.twitch.tv", "https://www.twitch.tv/search?term={q}"),
    "globoplay": ("Globoplay", "https://globoplay.globo.com", "https://globoplay.globo.com/busca/?q={q}"),
    "disney+": ("Disney+", "https://www.disneyplus.com", None),
    "max": ("Max", "https://play.max.com", None),
    "crunchyroll": ("Crunchyroll", "https://www.crunchyroll.com", "https://www.crunchyroll.com/search?q={q}"),
    "deezer": ("Deezer", "https://www.deezer.com", "https://www.deezer.com/search/{path}"),
}
STREAMING_ALIASES = {
    "prime": "prime video",
    "amazon prime": "prime video",
    "amazon": "prime video",
    "disney": "disney+",
    "disney plus": "disney+",
    "hbo": "max",
    "hbo max": "max",
    "globo play": "globoplay",
}

# Serviços que muita gente usa pelo navegador: abrem direto, sem precisar de app.
WEB_SERVICES = {
    "google maps": "https://www.google.com/maps",
    "maps": "https://www.google.com/maps",
    "gmail": "https://mail.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google agenda": "https://calendar.google.com",
    "google calendar": "https://calendar.google.com",
    "google docs": "https://docs.google.com",
    "google planilhas": "https://sheets.google.com",
    "google tradutor": "https://translate.google.com",
    "google fotos": "https://photos.google.com",
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "youtube music": "https://music.youtube.com",
    "claude": "https://claude.ai",
    "chatgpt": "https://chatgpt.com",
    "gemini": "https://gemini.google.com",
    "perplexity": "https://www.perplexity.ai",
    "github": "https://github.com",
    "linkedin": "https://www.linkedin.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "x": "https://x.com",
    "twitter": "https://x.com",
    "whatsapp web": "https://web.whatsapp.com",
    "outlook web": "https://outlook.live.com",
    "notion": "https://www.notion.so",
    "canva": "https://www.canva.com",
    "figma": "https://www.figma.com",
    "wikipedia": "https://pt.wikipedia.org",
    "mercado livre": "https://www.mercadolivre.com.br",
}

SHORTCUTS_FILE = Path(__file__).resolve().parent / "atalhos.json"

KNOWN_FOLDERS = {
    # nome normalizado: (GUID do Known Folder do Windows, pasta padrão relativa ao home)
    "downloads": ("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads"),
    "documentos": ("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", "Documents"),
    "documents": ("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", "Documents"),
    "area de trabalho": ("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "Desktop"),
    "desktop": ("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "Desktop"),
    "imagens": ("{33E28130-4E1E-4676-835A-98395C3BC3BB}", "Pictures"),
    "fotos": ("{33E28130-4E1E-4676-835A-98395C3BC3BB}", "Pictures"),
    "pictures": ("{33E28130-4E1E-4676-835A-98395C3BC3BB}", "Pictures"),
    "musicas": ("{4BD8D571-6D19-48D3-BE97-422220080E43}", "Music"),
    "music": ("{4BD8D571-6D19-48D3-BE97-422220080E43}", "Music"),
    "videos": ("{18989B1D-99B5-455B-841C-AB7C74E4DDFC}", "Videos"),
}

_APPS_CACHE: tuple[float, list[dict[str, str]]] | None = None
APPS_CACHE_SECONDS = 600


class PCControlError(Exception):
    """User-facing failure of a desktop action (message is safe to speak)."""


@dataclass(frozen=True)
class SavedPosition:
    placement: win_desktop.Placement
    monitor: int | None


@dataclass
class WindowMemory:
    """What Jarvis remembers about windows while it runs (keys are hwnds)."""

    positions: dict[int, list[SavedPosition]] = field(default_factory=dict)  # antes de cada move, para 'back'
    labels: dict[int, set[str]] = field(default_factory=dict)  # janelas que o Jarvis abriu → nomes pedidos
    hud_windows: set[int] = field(default_factory=set)  # janelas de navegador onde o HUD já apareceu


MEMORY = WindowMemory()


# ───────────────────────── helpers ─────────────────────────


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped.replace("​", "")).strip().lower()


def is_blocked_app(name: str) -> bool:
    normalized = normalize(name)
    return any(word in normalized for word in BLOCKED_APP_WORDS)


def best_match(query: str, names: list[str]) -> str | None:
    """Pick the closest name: exact, then prefix/substring (shortest), then fuzzy."""
    target = normalize(query)
    if not target:
        return None
    normalized = {name: normalize(name) for name in names}
    for name, value in normalized.items():
        if value == target:
            return name
    contains = [name for name, value in normalized.items() if value.startswith(target) or f" {target}" in f" {value}"]
    if contains:
        return min(contains, key=len)
    loose = [name for name, value in normalized.items() if target in value]
    if loose:
        return min(loose, key=len)
    close = difflib.get_close_matches(target, list(normalized.values()), n=1, cutoff=0.72)
    if close:
        return next(name for name, value in normalized.items() if value == close[0])
    return None


def normalize_url(target: str) -> str:
    candidate = target.strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", candidate, re.IGNORECASE):
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise PCControlError("Só abro endereços http ou https.")
    host = parsed.hostname or ""
    if not host or " " in parsed.netloc or ("." not in host and host != "localhost"):
        raise PCControlError("Isso não parece um endereço de site válido.")
    return candidate


def load_shortcuts() -> dict[str, str]:
    """Personal shortcuts (name → URL) saved by voice or edited in atalhos.json."""
    try:
        data = json.loads(SHORTCUTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}


def save_shortcut_entry(name: str, url: str) -> tuple[str, str]:
    label = name.strip()
    if not label or len(label) > 60:
        raise PCControlError("Diga um nome curto para o atalho.")
    target = normalize_url(url)
    shortcuts = load_shortcuts()
    shortcuts[label] = target
    SHORTCUTS_FILE.write_text(json.dumps(shortcuts, ensure_ascii=False, indent=2), encoding="utf-8")
    return label, target


def resolve_site(target: str) -> tuple[str, str]:
    """Turn a URL, a domain, a personal shortcut or a known service name into (label, url)."""
    text = target.strip()
    looks_like_url = "://" in text or ("." in text and " " not in text)
    if looks_like_url:
        url = normalize_url(text)
        return host_of(url), url

    shortcuts = load_shortcuts()
    match = best_match(text, list(shortcuts))
    if match:
        return match, normalize_url(shortcuts[match])
    key = APP_NAME_ALIASES.get(normalize(text), normalize(text))
    match = best_match(key, list(WEB_SERVICES))
    if match:
        return match.title(), WEB_SERVICES[match]
    raise PCControlError(
        f"Não sei o endereço de '{target}'. Pesquise com search_web e abra a URL oficial encontrada."
    )


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")


def _require_windows(feature: str) -> None:
    if not IS_WINDOWS:
        raise PCControlError(f"{feature} só está disponível no Windows por enquanto.")


def _poll(seconds: float) -> Iterator[int]:
    """Yield the step number about every POLL_SECONDS for `seconds` (at least once, no initial wait)."""
    for step in range(max(1, int(seconds / POLL_SECONDS))):
        if step:
            time.sleep(POLL_SECONDS)
        yield step


def _desktop_windows() -> list[win_desktop.Window]:
    """Visible windows; also remembers which browser windows have shown the HUD tab."""
    found = win_desktop.windows()
    MEMORY.hud_windows.update(window.hwnd for window in found if HUD_TITLE in window.title)
    return found


def _remember_opened(hwnd: int, *names: str) -> None:
    """Tie a window Jarvis just opened to the names used for it, so it is found before its title loads."""
    labels = MEMORY.labels.pop(hwnd, set())
    for name in names:
        value = normalize(name)
        if not value:
            continue
        labels.add(value)
        host = value.removeprefix("www.")
        if "." in host and " " not in host:
            labels.update({host, host.split(".")[0]})
    MEMORY.labels[hwnd] = labels
    while len(MEMORY.labels) > MAX_REMEMBERED_WINDOWS:
        MEMORY.labels.pop(next(iter(MEMORY.labels)))


def _jarvis_ancestor_names() -> set[str]:
    """Names of the processes that host this agent (terminal, IDE, python...)."""
    names: set[str] = set()
    try:
        current = psutil.Process()
        names.add(current.name().lower())
        for parent in current.parents():
            names.add(parent.name().lower())
    except psutil.Error:
        pass
    return names


# ───────────────────────── apps ─────────────────────────


def list_start_apps() -> list[dict[str, str]]:
    global _APPS_CACHE
    if not IS_WINDOWS:
        return []
    if _APPS_CACHE and time.time() - _APPS_CACHE[0] < APPS_CACHE_SECONDS:
        return _APPS_CACHE[1]

    command = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        timeout=25,
        creationflags=NO_WINDOW,
        check=False,
    )
    try:
        data = json.loads(result.stdout.decode("utf-8", "replace") or "[]")
    except json.JSONDecodeError:
        data = []
    if isinstance(data, dict):
        data = [data]
    apps = [
        {"name": item["Name"], "app_id": item["AppID"]}
        for item in data
        if item.get("Name") and item.get("AppID") and not is_blocked_app(item["Name"])
    ]
    _APPS_CACHE = (time.time(), apps)
    return apps


def resolve_app(name: str) -> tuple[str, str, bool]:
    """(label, target, is_site): what os.startfile opens, or the site URL when no app is installed."""
    builtin = BUILTIN_APPS.get(normalize(name))
    if builtin:
        return name.strip().capitalize(), builtin, False
    if is_blocked_app(name):
        raise PCControlError("Por segurança, não abro instaladores nem desinstaladores.")
    apps = list_start_apps()
    names = [app["name"] for app in apps]
    match = best_match(APP_NAME_ALIASES.get(normalize(name), name), names) or best_match(name, names)
    if match is None:
        try:
            label, url = resolve_site(name)
        except PCControlError:
            raise PCControlError(f"Não encontrei nenhum app ou site conhecido chamado '{name}'.") from None
        return label, url, True
    app_id = next(app["app_id"] for app in apps if app["name"] == match)
    return match, f"shell:AppsFolder\\{app_id}", False


def _is_app_window(window: win_desktop.Window, names: tuple[str, ...]) -> tuple[bool, bool]:
    """(matches, by_process) for a window of the app known by any of `names`."""
    if HUD_TITLE in window.title:
        return False, False
    queries = {normalize(APP_NAME_ALIASES.get(normalize(n), n)) for n in names} - {""}
    if window.process in _matching_exes_for(queries, {window.process}):
        return True, True
    title = normalize(window.title)
    return any(query in title for query in queries), False


def _matching_exes_for(queries: set[str], exes: set[str]) -> set[str]:
    return {exe for query in queries for exe in _matching_exes(query, exes, fuzzy=False)}


def _wait_for_app_window(
    names: tuple[str, ...], before: set[int], relaunch: Any = None
) -> tuple[win_desktop.Window | None, bool]:
    """(window, already_open): a new window of the app, or after a grace period one that already existed.

    Windows of the app's own process beat windows that only mention it in the title
    (e.g. a browser tab called "Claude" vs. the Claude app).
    """
    reuse_step = int(APP_REUSE_AFTER_SECONDS / POLL_SECONDS)
    relaunch_step = int(APP_RELAUNCH_AFTER_SECONDS / POLL_SECONDS)
    for step in _poll(APP_WINDOW_SECONDS):
        ranked = []
        for window in _desktop_windows():
            matches, by_process = _is_app_window(window, names)
            if matches:
                ranked.append((window.hwnd in before, not by_process, window))
        ranked.sort(key=lambda item: item[:2])
        new = [item for item in ranked if not item[0]]
        if new:
            return new[0][2], False
        if ranked and step >= reuse_step:
            return ranked[0][2], True
        if relaunch is not None and step == relaunch_step:
            # Apps escondidos na bandeja (Discord, Steam...) às vezes só reaparecem no segundo pedido.
            relaunch()
    return None, False


def launch_app(name: str, monitor: int | None = None) -> str:
    """Open an app, confirm a visible window appeared and bring it to the front (or to `monitor`)."""
    _require_windows("Abrir apps")
    screen = pick_monitor(monitor) if monitor is not None else None
    label, target, is_site = resolve_app(name)
    if is_site:
        if screen is not None:
            return open_in_new_window(label, target, screen.number)
        webbrowser.open(target, 2)
        return f"Abri {label} no navegador (é um site, não um app instalado)."

    names = (name, label, target) if target in BUILTIN_APPS.values() else (name, label)
    running_before = bool(_app_processes(name, label))
    before = {window.hwnd for window in _desktop_windows()}

    def start() -> None:
        os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606

    start()
    window, already_open = _wait_for_app_window(names, before, relaunch=start if running_before else None)
    seconds = int(APP_WINDOW_SECONDS)
    if window is None:
        running = _app_processes(name, label)
        if running:
            return (
                f"Pedi para abrir {label}, mas nenhuma janela apareceu em {seconds} s. O processo "
                f"({', '.join(running)}) está rodando, então deve estar escondido na bandeja, perto do relógio. "
                "Não posso confirmar que a janela abriu."
            )
        return (
            f"Pedi ao Windows para abrir {label}, mas nenhuma janela apareceu em {seconds} s; "
            "pode ainda estar carregando. Não posso confirmar que abriu."
        )

    _remember_opened(window.hwnd, name, label)
    opening = f"{label} já estava aberto" if already_open else f"Abri {label}"
    if screen is not None:
        return f"{opening}. {_move_window(window, screen)}"
    landed = win_desktop.window_monitor(window.hwnd)
    where = f" na tela {landed.number}" if landed else ""
    if not win_desktop.bring_to_front(window.hwnd):
        return f"{opening}; a janela está{where}, mas o Windows não deixou trazê-la para frente."
    return f"{opening}; a janela '{_clean_title(window.title)}' está em primeiro plano{where}."


def _running_processes() -> set[str]:
    """Executable names (lowercase) of the current user's processes."""
    try:
        me = psutil.Process().username()
    except psutil.Error:
        me = None

    running: set[str] = set()
    for proc in psutil.process_iter(["name", "username"]):
        info = proc.info
        if not info.get("name") or (me and info.get("username") != me):
            continue
        running.add(info["name"].lower())
    return running


def _matching_exes(name: str, exes: set[str], fuzzy: bool = True) -> list[str]:
    """Which of `exes` belong to the app called `name` (alias, then substring, then fuzzy)."""
    wanted = PROCESS_ALIASES.get(normalize(name))
    if wanted:
        return sorted(exe for exe in wanted if exe in exes)

    target = normalize(name).replace(" ", "")
    matches = [exe for exe in exes if target and target in exe.removesuffix(".exe").replace(" ", "")]
    if not matches and fuzzy and target:
        close = difflib.get_close_matches(target, [exe.removesuffix(".exe") for exe in exes], n=1, cutoff=0.75)
        matches = [f"{close[0]}.exe"] if close else []
    return sorted(matches)


def find_processes(name: str) -> list[str]:
    """Executable names (lowercase) of the current user's processes matching `name`."""
    return _matching_exes(name, _running_processes())


def _app_processes(*names: str) -> list[str]:
    """Running processes of the app, trying each of its names in turn."""
    running = _running_processes()
    return next((found for found in (_matching_exes(name, running) for name in names) if found), [])


def hud_browser_processes() -> set[str]:
    """Browser executables whose active tab is the Jarvis HUD."""
    return {window.process for window in _desktop_windows() if HUD_TITLE in window.title}


def _confirm_closed(name: str, exes: list[str]) -> str:
    """Wait for the processes to really exit and say what actually happened."""
    still = set(exes)
    for _ in _poll(CLOSE_WAIT_SECONDS):
        still = set(exes) & _running_processes()
        if not still:
            return f"Fechei {name}; o processo ({', '.join(exes)}) encerrou."
    left = ", ".join(sorted(still))
    if any(window.process in still for window in _desktop_windows()):
        return (
            f"Pedi para fechar {name}, mas a janela continua aberta ({left} rodando); "
            "talvez esteja pedindo para salvar ou confirmar algo."
        )
    return (
        f"A janela de {name} fechou, mas o processo ({left}) continua rodando em segundo plano, "
        "provavelmente na bandeja perto do relógio."
    )


def close_app_processes(name: str) -> str:
    targets = find_processes(name)
    if not targets:
        raise PCControlError(f"Não encontrei '{name}' aberto.")

    protected = PROTECTED_PROCESSES | _jarvis_ancestor_names()
    blocked = [exe for exe in targets if exe in protected]
    if blocked:
        raise PCControlError(
            f"Não posso fechar {', '.join(blocked)}: é um processo do sistema ou do próprio Jarvis."
        )
    hud_hosts = hud_browser_processes() & set(targets)
    if hud_hosts:
        raise PCControlError(
            "O HUD do Jarvis está aberto nesse navegador. Feche as abas uma a uma em vez do navegador inteiro."
        )

    closed: list[str] = []
    for exe in targets:
        if IS_WINDOWS:
            # Sem /F: o app recebe um pedido normal de fechar e pode salvar o trabalho.
            result = subprocess.run(
                ["taskkill", "/IM", exe],
                capture_output=True,
                creationflags=NO_WINDOW,
                check=False,
            )
            if result.returncode == 0:
                closed.append(exe)
        else:
            for proc in psutil.process_iter(["name"]):
                if (proc.info.get("name") or "").lower() == exe:
                    proc.terminate()
            closed.append(exe)
    if not closed:
        raise PCControlError(f"'{name}' não aceitou fechar normalmente.")
    return _confirm_closed(name, closed)


# ───────────────────────── browser & media ─────────────────────────


def _clean_title(title: str) -> str:
    return title.replace("\u200b", "").strip()


def _browser_windows() -> list[win_desktop.Window]:
    # Ordem Z: a primeira janela é a usada mais recentemente.
    return [window for window in _desktop_windows() if window.process in BROWSER_PROCESSES]


def _active_title() -> str:
    return _clean_title(win_desktop.foreground_title())


# Último conteúdo que o Jarvis abriu ("where": browser ou app), para fechar a aba certa depois.
_LAST_MEDIA: dict[str, str] | None = None

# "Fecha a aba de reprodução / o vídeo / a live que você abriu" aponta para a última mídia aberta.
MEDIA_TAB_WORDS = re.compile(
    r"\b(?:reproducao|video|videos|midia|musica|player|live|transmissao|tocando|abriu|aberta|aberto|ultima|ultimo)\b"
)
TAB_FILLER = re.compile(r"\b(?:a|o|aba|guia|do|da|de|no|na)\b")


def remember_media(service: str, title: str, url: str = "", where: str = "browser") -> None:
    global _LAST_MEDIA
    _LAST_MEDIA = {"service": service, "title": title, "url": url, "host": host_of(url), "where": where}


def media_tab_targets(name: str) -> list[str]:
    """Texts to look for in tab titles, most specific first.

    A generic name ("aba de reprodução") or the service of the last media Jarvis opened
    ("YouTube") tries that media's exact title first, so the right one of several tabs closes.
    """
    text = normalize(name)
    media = _LAST_MEDIA
    if not media or media["where"] != "browser":
        return [text]
    title = normalize(media["title"])
    service = normalize(media["service"])
    core = re.sub(r"\s+", " ", TAB_FILLER.sub(" ", text)).strip()  # "aba do YouTube" -> "youtube"
    if MEDIA_TAB_WORDS.search(text):
        targets = [title, service]
    elif core in {service, normalize(media["host"])}:
        targets = [title, core]
    else:
        targets = [text]
    return [target for target in dict.fromkeys(targets) if target]


def _media_hint() -> str:
    media = _LAST_MEDIA
    if not media:
        return ""
    if media["where"] == "app":
        return (
            f" O que abri por último foi o app do {media['service']}, não uma aba: para fechá-lo use "
            f"close_app('{media['service']}')."
        )
    return f" A última mídia que abri foi '{media['title']}' ({media['service']})."


def _forget_media_tab(tab_title: str) -> None:
    global _LAST_MEDIA
    media = _LAST_MEDIA
    if media and media["where"] == "browser" and normalize(media["title"]) in normalize(tab_title):
        _LAST_MEDIA = None


def _find_tab(windows: list[win_desktop.Window], target: str, action: str) -> str | None:
    import pyautogui

    for window in windows:
        if not win_desktop.bring_to_front(window.hwnd):
            continue
        first = _active_title()
        title = first
        for _ in range(40):
            if target in normalize(title) and HUD_TITLE not in title:
                if action == "close":
                    pyautogui.hotkey("ctrl", "w")
                    _forget_media_tab(title)
                    return f"Fechei a aba '{title}'."
                return f"Aba '{title}' em primeiro plano."
            pyautogui.hotkey("ctrl", "tab")
            time.sleep(0.25)
            title = _active_title()
            if title == first:
                break
    return None


def browser_tab_action(action: str, name: str | None = None) -> str:
    _require_windows("Controlar abas")
    import pyautogui

    windows = _browser_windows()
    if not windows:
        raise PCControlError("Não encontrei nenhuma janela de navegador aberta." + _media_hint())

    if action in {"close", "switch"} and name:
        for target in media_tab_targets(name):
            result = _find_tab(windows, target, action)
            if result:
                return result
        raise PCControlError(f"Não encontrei nenhuma aba com '{name}' no título." + _media_hint())

    window = windows[0]
    if not win_desktop.bring_to_front(window.hwnd):
        raise PCControlError("O Windows não deixou focar a janela do navegador. Clique nela uma vez e peça de novo.")

    if action == "close":
        title = _active_title()
        if HUD_TITLE in title:
            raise PCControlError("A aba ativa é o próprio HUD. Diga o nome da aba que devo fechar." + _media_hint())
        pyautogui.hotkey("ctrl", "w")
        _forget_media_tab(title)
        return f"Fechei a aba '{title}'."

    hotkeys = {
        "new": ("ctrl", "t"),
        "next": ("ctrl", "tab"),
        "previous": ("ctrl", "shift", "tab"),
        "reopen": ("ctrl", "shift", "t"),
    }
    if action not in hotkeys:
        raise PCControlError(f"Ação de aba desconhecida: {action}.")
    pyautogui.hotkey(*hotkeys[action])
    time.sleep(0.25)
    return f"Feito. Aba atual: '{_active_title()}'."


# ───────────────────────── windows & monitors ─────────────────────────


def _matching_windows(target: str) -> list[win_desktop.Window]:
    """Windows for `target`, best first: opened by Jarvis under that name, title, app, fuzzy title."""
    windows = [window for window in _desktop_windows() if HUD_TITLE not in window.title]
    query = normalize(APP_NAME_ALIASES.get(normalize(target), target))
    if not query:
        return []
    opened = [window for window in windows if query in MEMORY.labels.get(window.hwnd, ())]
    by_title = [window for window in windows if query in normalize(window.title)]
    processes = set(_matching_exes(query, {window.process for window in windows}))
    by_process = [window for window in windows if window.process in processes]
    close = best_match(query, [window.title for window in windows])
    fuzzy = [window for window in windows if close and window.title == close]
    return list({window.hwnd: window for window in opened + by_title + by_process + fuzzy}.values())


def find_window(target: str, wait: float = 0.0) -> win_desktop.Window:
    """Most likely window for `target`, waiting up to `wait` seconds for one that is still opening."""
    for _ in _poll(wait):
        matches = _matching_windows(target)
        if matches:
            return matches[0]
    raise PCControlError(f"Não encontrei nenhuma janela aberta de '{target}'.")


def pick_monitor(number: int | None) -> win_desktop.Monitor:
    screens = win_desktop.monitors()
    if not screens:
        raise PCControlError("Não consegui ler os monitores.")
    if number is None:
        return next((m for m in screens if m.primary), screens[0])
    for monitor in screens:
        if monitor.number == number:
            return monitor
    numbers = ", ".join(str(m.number) for m in screens)
    raise PCControlError(f"Não existe tela {number}. Telas disponíveis: {numbers}.")


def _remember_position(hwnd: int) -> None:
    """Save where the window is before Jarvis moves it, so 'back' can undo the move."""
    placement = win_desktop.get_placement(hwnd)
    if placement is None:
        return
    screen = win_desktop.window_monitor(hwnd) or win_desktop.monitor_for_rect(placement.normal, win_desktop.monitors())
    stack = MEMORY.positions.pop(hwnd, [])  # reinserir deixa a janela movida por último no fim
    MEMORY.positions[hwnd] = [*stack, SavedPosition(placement, screen.number if screen else None)][
        -MAX_SAVED_POSITIONS:
    ]
    while len(MEMORY.positions) > MAX_REMEMBERED_WINDOWS:
        MEMORY.positions.pop(next(iter(MEMORY.positions)))


def _hud_note(hwnd: int) -> str:
    if hwnd in MEMORY.hud_windows:
        return " O HUD do Jarvis está numa aba dessa mesma janela e foi junto."
    return ""


def _landed(hwnd: int, title: str, wanted: int | None, verb: str) -> tuple[int | None, str]:
    """(monitor the window really is on, problem to report) — never trust the monitor we only asked for."""
    screen = win_desktop.window_monitor(hwnd)
    if screen is None:
        return None, f"Tentei {verb} '{title}', mas não consegui confirmar em que tela ela ficou."
    if wanted is not None and screen.number != wanted:
        return screen.number, f"Tentei {verb} '{title}' para a tela {wanted}, mas ela ficou na tela {screen.number}."
    return screen.number, ""


def _move_window(window: win_desktop.Window, screen: win_desktop.Monitor, maximize: bool | None = None) -> str:
    _remember_position(window.hwnd)
    win_desktop.move_to_monitor(window.hwnd, screen, maximize=maximize)
    title = _clean_title(window.title)
    number, problem = _landed(window.hwnd, title, screen.number, "levar")
    state = " e maximizada" if maximize else ""
    return problem or f"'{title}' agora está na tela {number}{state}.{_hud_note(window.hwnd)}"


def _move_back(target: str) -> str:
    candidates = _matching_windows(target)
    window = next((w for w in candidates if MEMORY.positions.get(w.hwnd)), None)
    if window is None:
        if not candidates:
            raise PCControlError(f"Não encontrei nenhuma janela aberta de '{target}'.")
        raise PCControlError(
            f"Não tenho registro de onde '{_clean_title(candidates[0].title)}' estava antes: só lembro das "
            "janelas que eu mesmo movi. Pergunte para qual tela devo levá-la."
        )
    stack = MEMORY.positions[window.hwnd]
    saved = stack.pop()
    if not stack:
        del MEMORY.positions[window.hwnd]
    win_desktop.restore_placement(window.hwnd, saved.placement)
    title = _clean_title(window.title)
    number, problem = _landed(window.hwnd, title, saved.monitor, "devolver")
    state = ", maximizada" if saved.placement.maximized else ""
    return problem or f"'{title}' voltou para onde estava: tela {number}{state}.{_hud_note(window.hwnd)}"


def window_action(target: str, action: str, monitor: int | None) -> str:
    _require_windows("Controlar janelas")
    if action == "back":
        return _move_back(target)
    window = find_window(target, wait=FIND_WINDOW_SECONDS)
    protected = PROTECTED_PROCESSES | _jarvis_ancestor_names()

    if action == "move":
        if monitor is None:
            raise PCControlError(
                "Diga para qual tela devo mover a janela. Para devolvê-la aonde estava, use a ação 'back'."
            )
        return _move_window(window, pick_monitor(monitor))
    if action == "maximize":
        if monitor is not None:
            return _move_window(window, pick_monitor(monitor), maximize=True)
        _remember_position(window.hwnd)
        win_desktop.show_window(window.hwnd, win_desktop.SW_MAXIMIZE)
        win_desktop.bring_to_front(window.hwnd)
        screen = win_desktop.window_monitor(window.hwnd)
        where = f" na tela {screen.number}" if screen else ""
        return f"'{window.title}' maximizada{where}."
    if action == "minimize":
        win_desktop.show_window(window.hwnd, win_desktop.SW_MINIMIZE)
        return f"'{window.title}' minimizada."
    if action in {"restore", "focus"}:
        win_desktop.show_window(window.hwnd, win_desktop.SW_RESTORE)
        if not win_desktop.bring_to_front(window.hwnd):
            raise PCControlError("O Windows não deixou trazer essa janela para frente.")
        return f"'{window.title}' em primeiro plano."
    if action in {"snap_left", "snap_right"}:
        import pyautogui

        if not win_desktop.bring_to_front(window.hwnd):
            raise PCControlError("O Windows não deixou focar essa janela.")
        _remember_position(window.hwnd)
        pyautogui.hotkey("win", "left" if action == "snap_left" else "right")
        return f"'{window.title}' encaixada à {'esquerda' if action == 'snap_left' else 'direita'}."
    if action == "close":
        if window.process in protected:
            raise PCControlError("Essa janela pertence ao sistema ou ao próprio Jarvis.")
        win_desktop.close_window(window.hwnd)
        return f"Pedi para fechar a janela '{window.title}'."
    raise PCControlError(f"Ação de janela desconhecida: {action}.")


def command_executable(command: str) -> str:
    """Executable of a registry 'open' command such as '"C:\\...\\msedge.exe" --single-argument %1'."""
    command = command.strip()
    if command.startswith('"'):
        return command[1:].split('"', 1)[0]
    return command.split(" ", 1)[0]


def default_browser() -> Path | None:
    """The default web browser's executable (only well-known browsers), falling back to Edge."""
    if not IS_WINDOWS:
        return None
    import winreg

    candidates: list[str] = []
    for key_path in DEFAULT_BROWSER_KEYS:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                prog_id = winreg.QueryValueEx(key, "ProgId")[0]
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command") as key:
                candidates.append(command_executable(winreg.QueryValueEx(key, "")[0]))
            break
        except OSError:
            continue
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, EDGE_APP_PATH) as key:
            candidates.append(winreg.QueryValueEx(key, "")[0])
    except OSError:
        pass
    for candidate in candidates:
        path = Path(candidate)
        if path.name.lower() in BROWSER_PROCESSES and path.is_file():
            return path
    return None


def new_window_command(browser: Path, url: str) -> list[str]:
    """Fixed command line that opens one validated http(s) URL in a new browser window."""
    target = normalize_url(url)  # só http(s) chega à linha de comando, nunca uma opção do navegador
    flag = "-new-window" if browser.name.lower() == "firefox.exe" else "--new-window"
    return [str(browser), flag, target]


def _is_placeholder(title: str) -> bool:
    value = normalize(_clean_title(title))
    return not value or value.startswith(PLACEHOLDER_TITLES)


def _wait_for_browser_window(process: str, before: set[int]) -> win_desktop.Window | None:
    """New window of `process` once its title stops being 'Nova guia'/loading (or time runs out)."""
    window: win_desktop.Window | None = None
    last_title: str | None = None
    for _ in _poll(SITE_WINDOW_SECONDS):
        if window is None:
            window = next((w for w in _desktop_windows() if w.process == process and w.hwnd not in before), None)
            if window is None:
                continue
        title = _clean_title(win_desktop.window_title(window.hwnd))
        if title == last_title and not _is_placeholder(title):
            break
        last_title = title
    if window is None:
        return None
    return replace(window, title=last_title or window.title)


def open_in_new_window(label: str, url: str, monitor: int) -> str:
    """Open a site in its own browser window and move it to `monitor`.

    A tab would land in an existing window — often the one holding the HUD — and moving
    that window would drag the HUD along, so a dedicated window is opened instead.
    """
    _require_windows("Abrir sites em outra tela")
    screen = pick_monitor(monitor)
    browser = default_browser()
    if browser is None:
        webbrowser.open(url, 2)
        return (
            f"Abri {label} numa aba do navegador, mas não consegui abrir uma janela separada; "
            f"não movi para a tela {screen.number} para não levar o HUD junto."
        )
    command = new_window_command(browser, url)
    before = {window.hwnd for window in _desktop_windows()}
    subprocess.Popen(command, creationflags=NO_WINDOW, close_fds=True)  # noqa: S603 — executável e URL validados
    window = _wait_for_browser_window(browser.name.lower(), before)
    if window is None:
        return (
            f"Pedi ao navegador para abrir {label} numa janela nova, mas ela não apareceu em "
            f"{int(SITE_WINDOW_SECONDS)} s, então não a movi para a tela {screen.number}."
        )
    _remember_opened(window.hwnd, label, host_of(command[-1]))
    return f"Abri {label} numa janela nova do navegador. {_move_window(window, screen)}"


def open_url(label: str, url: str, monitor: int | None) -> str:
    """New tab in the current browser window, or a window of its own on `monitor`."""
    if monitor is not None:
        return open_in_new_window(label, url, monitor)
    webbrowser.open(url, 2)
    return f"Abri {label} no navegador."


def capture_screen(monitor: int | None, window: str | None = None) -> tuple[Any, str]:
    _require_windows("Ler a tela")
    if window:
        target = find_window(window)
        win_desktop.bring_to_front(target.hwnd)
        time.sleep(0.35)  # deixa a janela terminar de redesenhar antes do print
        return win_desktop.grab_region(win_desktop.window_rect(target.hwnd)), f"janela '{target.title}'"
    screen = pick_monitor(monitor) if monitor is not None else None
    image = win_desktop.grab_monitor(screen)
    return image, f"tela {screen.number}" if screen else "todas as telas"


def press_media_key(action: str) -> None:
    import pyautogui

    keys = {"play_pause": "playpause", "next": "nexttrack", "previous": "prevtrack", "stop": "stop"}
    if action not in keys:
        raise PCControlError(f"Ação de mídia desconhecida: {action}.")
    pyautogui.press(keys[action])


def change_volume(action: str, level: int | None) -> int:
    _require_windows("Controlar o volume")
    import comtypes
    from pycaw.pycaw import AudioUtilities

    comtypes.CoInitialize()
    try:
        endpoint = AudioUtilities.GetSpeakers().EndpointVolume
        current = round(endpoint.GetMasterVolumeLevelScalar() * 100)
        if action == "mute":
            endpoint.SetMute(1, None)
            return current
        if action == "unmute":
            endpoint.SetMute(0, None)
            return current
        if action == "set":
            if level is None:
                raise PCControlError("Diga o nível do volume, de 0 a 100.")
            target = level
        elif action == "up":
            target = current + (level or 10)
        elif action == "down":
            target = current - (level or 10)
        else:
            raise PCControlError(f"Ação de volume desconhecida: {action}.")
        target = max(0, min(100, int(target)))
        endpoint.SetMute(0, None)
        endpoint.SetMasterVolumeLevelScalar(target / 100, None)
        return target
    finally:
        comtypes.CoUninitialize()


def resolve_folder(folder: str) -> Path:
    key = normalize(folder)
    if key not in KNOWN_FOLDERS:
        options = "Downloads, Documentos, Área de trabalho, Imagens, Músicas ou Vídeos"
        raise PCControlError(f"Só abro pastas conhecidas: {options}.")
    guid, fallback = KNOWN_FOLDERS[key]
    if IS_WINDOWS:
        import ctypes

        from comtypes import GUID

        path_ptr = ctypes.c_wchar_p()
        folder_id = GUID(guid)
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(path_ptr)) == 0:
            path = Path(path_ptr.value or "")
            ctypes.windll.ole32.CoTaskMemFree(path_ptr)
            if path.exists():
                return path
    return Path.home() / fallback


def open_path(path: Path) -> None:
    if IS_WINDOWS:
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


# ───────────────────────── media lookup ─────────────────────────

YOUTUBE_LIVE_FILTER = "EgJAAQ=="  # filtro "Ao vivo" da busca do YouTube (parâmetro sp)
# Pedido claro de live ("a live do Gaules", "ao vivo"); "Live and Let Die" continua sendo música.
LIVE_REQUEST = re.compile(
    r"\b(?:ao vivo|aovivo|transmissao ao vivo|(?:a|na|uma|essa|em) live|lives? (?:do|da|de|dos|das))\b"
)
LIVE_WORDS = re.compile(r"\b(?:ao vivo|aovivo|live|lives|livestream|transmissao|transmissoes|stream|streaming)\b")
SUBJECT_FILLER = re.compile(r"\b(?:a|o|as|os|do|da|dos|das|de|no|na|nos|nas|em|agora|hoje|canal|youtube|twitch)\b")
TWITCH_LOGIN = re.compile(r"[a-z0-9_]{3,25}")
SPOTIFY_LINK = re.compile(
    r"open\.spotify\.com/(?:intl-[a-z]{2}(?:-[a-z]{2})?/)?(track|album|playlist|artist)/([A-Za-z0-9]{22})",
    re.IGNORECASE,
)
SPOTIFY_TITLE_SUFFIX = re.compile(r"\s*[|\-–]\s*Spotify(?:\s+Playlist)?\s*$", re.IGNORECASE)
SPOTIFY_TITLE_BY = re.compile(
    r"^(?P<name>.+?) - (?:song(?: and lyrics)?|m[uú]sica(?: e letra)?|album|[aá]lbum|single|ep|compilation"
    r"|compila[cç][aã]o|playlist) (?:by|de|por) (?P<artist>.+)$",
    re.IGNORECASE,
)
# Ordem de preferência: faixas e álbuns costumam começar a tocar quando o app abre o link.
SPOTIFY_KINDS = ("track", "album", "playlist", "artist")
SPOTIFY_KIND_LABELS = {"track": "a faixa", "album": "o álbum", "playlist": "a playlist", "artist": "a página do artista"}
SPOTIFY_IDLE_TITLES = {"spotify", "spotify free", "spotify premium"}
SPOTIFY_POLL_SECONDS = 0.4
SPOTIFY_START_SECONDS = 8.0
SPOTIFY_COLD_START_SECONDS = 15.0  # o app ainda vai abrir
SPOTIFY_PLAY_SECONDS = 4.0


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize(text))


def mentions(subject: str, text: str) -> bool:
    """True when every word of `subject` appears in `text`, ignoring accents, case and punctuation."""
    words = [_compact(word) for word in normalize(subject).split()]
    words = [word for word in words if word]
    haystack = _compact(text)
    return bool(words) and all(word in haystack for word in words)


def wants_live(text: str) -> bool:
    return bool(LIVE_REQUEST.search(normalize(text)))


def live_subject(text: str) -> str:
    """'live do Gaules' -> 'gaules': who or what the user wants to watch live."""
    cleaned = SUBJECT_FILLER.sub(" ", LIVE_WORDS.sub(" ", normalize(text)))
    return re.sub(r"\s+", " ", cleaned).strip() or normalize(text)


def _dicts(node: Any) -> Iterator[dict[str, Any]]:
    """Every dict inside a JSON tree, depth first (document order)."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _dicts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _dicts(value)


def _yt_text(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    if "simpleText" in node:
        return str(node["simpleText"])
    return "".join(str(run.get("text", "")) for run in node.get("runs", []) if isinstance(run, dict))


def _youtube_status(renderer: dict[str, Any]) -> str:
    badges = {
        str(badge.get("metadataBadgeRenderer", {}).get("style", ""))
        for badge in renderer.get("badges", [])
        if isinstance(badge, dict)
    }
    overlays = {
        str(overlay.get("thumbnailOverlayTimeStatusRenderer", {}).get("style", ""))
        for overlay in renderer.get("thumbnailOverlays", [])
        if isinstance(overlay, dict)
    }
    if "BADGE_STYLE_TYPE_LIVE_NOW" in badges or "LIVE" in overlays:
        return "live"
    if "upcomingEventData" in renderer or "UPCOMING" in overlays:
        return "upcoming"
    return "video"


def parse_youtube_results(html: str) -> list[dict[str, str]]:
    """Videos of a YouTube search page, in order, with title, channel and live status."""
    data = None
    start = re.search(r'ytInitialData"?\]?\s*=\s*(?=\{)', html)
    if start:
        try:
            data, _ = json.JSONDecoder().raw_decode(html, start.end())
        except ValueError:
            data = None

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in _dicts(data):
        renderer = node.get("videoRenderer")
        if not isinstance(renderer, dict):
            continue
        video_id = renderer.get("videoId")
        if not isinstance(video_id, str) or not re.fullmatch(r"[\w-]{11}", video_id) or video_id in seen:
            continue
        seen.add(video_id)
        results.append(
            {
                "id": video_id,
                "title": _yt_text(renderer.get("title")),
                "channel": _yt_text(renderer.get("ownerText")) or _yt_text(renderer.get("longBylineText")),
                "status": _youtube_status(renderer),
                "viewers": _yt_text(renderer.get("viewCountText")),
            }
        )
    if not results:
        # Formato desconhecido: fica só com o primeiro vídeo, sem saber se é ao vivo.
        match = re.search(r'"videoId":"([\w-]{11})"', html)
        if match:
            results.append({"id": match.group(1), "title": "", "channel": "", "status": "unknown", "viewers": ""})
    return results


def youtube_search(query: str, live: bool = False) -> list[dict[str, str]]:
    params = {"search_query": query, "hl": "pt-BR", "gl": "BR"}
    if live:
        params["sp"] = YOUTUBE_LIVE_FILTER
    response = requests.get(
        "https://www.youtube.com/results",
        params=params,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"},
        timeout=12,
    )
    response.raise_for_status()
    return parse_youtube_results(response.text)


def find_youtube_video(query: str, live: bool = False) -> dict[str, str] | None:
    """Best video for `query`. With `live`, only a stream that is live right now (or None)."""
    if live:
        subject = live_subject(query)
        lives = [result for result in youtube_search(subject, live=True) if result["status"] == "live"]
        pick = next((r for r in lives if mentions(subject, r["channel"])), None) or next(
            (r for r in lives if mentions(subject, r["title"])), None
        )
    else:
        results = youtube_search(query)
        pick = results[0] if results else None
    if pick is None:
        return None

    url = f"https://www.youtube.com/watch?v={pick['id']}"
    video = {
        "url": url,
        "title": pick["title"] or query,
        "channel": pick["channel"],
        "thumbnail": f"https://i.ytimg.com/vi/{pick['id']}/hqdefault.jpg",
        "status": pick["status"],
        "viewers": pick["viewers"],
    }
    if not pick["title"] or not pick["channel"]:
        try:
            meta = requests.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"},
                timeout=8,
            )
            if meta.ok:
                data = meta.json()
                video["title"] = pick["title"] or data.get("title") or query
                video["channel"] = pick["channel"] or data.get("author_name") or ""
        except (requests.RequestException, ValueError):
            pass
    return video


def describe_youtube(video: dict[str, str]) -> str:
    channel = f" do canal {video['channel']}" if video["channel"] else ""
    if video["status"] == "live":
        viewers = f", {video['viewers']}" if video["viewers"] else ""
        state = f" (ao vivo agora{viewers})"
    elif video["status"] == "upcoming":
        state = " (transmissão agendada: ainda não começou)"
    elif video["status"] == "video":
        state = " (vídeo gravado, não é ao vivo)"
    else:
        state = " (não consegui confirmar se é ao vivo)"
    return (
        f"Abri no YouTube: '{video['title']}'{channel}{state}. Diga que abriu: o navegador começa o vídeo, "
        "mas não confirmo o áudio. Para fechar depois, use browser_tab(action='close', "
        f"name={json.dumps(video['title'], ensure_ascii=False)})."
    )


def parse_twitch_channel(html: str, login: str) -> dict[str, Any] | None:
    """Channel name and live state from the public page's schema.org data (None: no such channel)."""
    name = ""
    live = False
    title = ""
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for node in _dicts(data):
            if node.get("@type") == "ProfilePage" and isinstance(node.get("mainEntity"), dict):
                name = name or str(node["mainEntity"].get("name") or "")
            publication = node.get("publication")
            if isinstance(publication, dict) and publication.get("isLiveBroadcast") is True:
                # O título da transmissão vem em "description"; "name" é só "Canal - Twitch".
                live = True
                title = title or str(node.get("description") or node.get("name") or "")
    if not name:
        return None
    rerun = live and normalize(title).startswith(("rerun", "reprise"))
    return {"login": login, "name": name, "live": live, "rerun": rerun, "title": title, "url": f"https://www.twitch.tv/{login}"}


def twitch_login(text: str) -> str | None:
    candidate = re.sub(r"[^a-z0-9_]", "", live_subject(text).replace(" ", ""))
    return candidate if TWITCH_LOGIN.fullmatch(candidate) else None


def lookup_twitch_channel(text: str) -> dict[str, Any] | None:
    login = twitch_login(text)
    if not login:
        return None
    try:
        response = requests.get(f"https://www.twitch.tv/{login}", headers={"User-Agent": USER_AGENT}, timeout=10)
    except requests.RequestException:
        return None
    return parse_twitch_channel(response.text, login) if response.ok else None


def twitch_summary(channel: dict[str, Any]) -> str:
    if channel["live"] and channel["rerun"]:
        return f"{channel['name']} está passando uma reprise na Twitch ('{channel['title']}'), não uma live ao vivo"
    if channel["live"]:
        return f"{channel['name']} está ao vivo na Twitch agora: '{channel['title']}'"
    return f"{channel['name']} está offline na Twitch agora"


def open_twitch(query: str) -> dict[str, Any]:
    channel = lookup_twitch_channel(query)
    if channel:
        url = channel["url"]
    else:
        url = STREAMING_SERVICES["twitch"][2].format(q=quote_plus(query), path=quote(query))  # type: ignore[union-attr]
    webbrowser.open(url, 2)
    return {"channel": channel, "url": url}


def describe_twitch(result: dict[str, Any], query: str) -> str:
    channel = result["channel"]
    if channel is None:
        return (
            f"Abri a busca da Twitch por '{query}'. Não confirmei nenhum canal ao vivo: o usuário escolhe o "
            "resultado. Não diga que está tocando."
        )
    return f"Abri o canal {channel['name']} na Twitch. {twitch_summary(channel)}."


def parse_spotify_result(href: str, title: str) -> dict[str, str] | None:
    """A Spotify link from a web search result, with the name and artist read from its title."""
    match = SPOTIFY_LINK.search(href or "")
    if not match:
        return None
    kind, item_id = match.group(1).lower(), match.group(2)
    text = SPOTIFY_TITLE_SUFFIX.sub("", (title or "").strip())
    name, artist = text, ""
    by = SPOTIFY_TITLE_BY.match(text)
    if by:
        name, artist = by["name"], by["artist"]
    return {
        "kind": kind,
        "id": item_id,
        "name": name.strip(),
        "artist": artist.strip(),
        "uri": f"spotify:{kind}:{item_id}",
        "url": f"https://open.spotify.com/{kind}/{item_id}",
    }


def find_spotify_items(query: str) -> list[dict[str, str]]:
    """Spotify links for `query` found by a web search (no Spotify account or API key needed)."""
    from ddgs import DDGS

    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for result in DDGS().text(f"{query} site:open.spotify.com", max_results=10, region="br-pt") or []:
        item = parse_spotify_result(str(result.get("href", "")), str(result.get("title", "")))
        if item and item["uri"] not in seen:
            seen.add(item["uri"])
            items.append(item)
    return items


def pick_spotify_item(query: str, items: list[dict[str, str]]) -> dict[str, str] | None:
    relevant = [item for item in items if mentions(query, f"{item['name']} {item['artist']}")]
    for kind in SPOTIFY_KINDS:
        for item in relevant:
            if item["kind"] == kind:
                return item
    return None


def spotify_app_installed() -> bool:
    if not IS_WINDOWS:
        return False
    if find_processes("spotify"):
        return True
    return any(normalize(app["name"]) == "spotify" for app in list_start_apps())


def _spotify_window() -> win_desktop.Window | None:
    for window in win_desktop.process_windows("spotify.exe"):
        title = _clean_title(window.title)
        if " - " in title or normalize(title) in SPOTIFY_IDLE_TITLES:
            return window
    return None


def spotify_now_playing() -> str | None:
    """'Artista - Música' while the desktop app plays, '' when paused or idle, None when unreadable.

    The Spotify app shows the current track in its window title and only its name when paused.
    """
    window = _spotify_window()
    if window is None:
        return None
    title = _clean_title(window.title)
    return "" if normalize(title) in SPOTIFY_IDLE_TITLES else title


def _spotify_confirms(now: str | None, item: dict[str, str], query: str, before: str | None) -> bool:
    if not now:
        return False
    names = [query, item["artist"]]
    if item["kind"] == "track":
        names.append(re.split(r" - | \(", item["name"])[0])
    if item["kind"] == "artist":
        names.append(item["name"])
    if any(name.strip() and mentions(name, now) for name in names):
        return True
    # Uma playlist pode ter qualquer artista: vale ter trocado de música depois de abrir o link.
    return item["kind"] == "playlist" and now != before


def _wait_for_spotify(
    item: dict[str, str], query: str, before: str | None, seconds: float, stop_on_any: bool = False
) -> str | None:
    now = spotify_now_playing()
    for _ in range(max(1, int(seconds / SPOTIFY_POLL_SECONDS))):
        if _spotify_confirms(now, item, query, before) or (stop_on_any and now):
            break
        time.sleep(SPOTIFY_POLL_SECONDS)
        now = spotify_now_playing()
    return now


def play_spotify(query: str) -> dict[str, Any]:
    """Try to really play `query` in the Spotify desktop app and check its window title afterwards.

    States: playing (confirmed), opened (opened but not confirmed), unverified (app title
    unreadable), search (only the search page), web (Spotify Web in the browser, no autoplay).
    """
    try:
        items = find_spotify_items(query)
    except Exception:
        logger.warning("A busca de links do Spotify falhou.", exc_info=True)
        items = []
    item = pick_spotify_item(query, items)
    url = item["url"] if item else f"https://open.spotify.com/search/{quote(query)}"
    result: dict[str, Any] = {"state": "web", "item": item, "url": url, "now": None}

    if not spotify_app_installed():
        webbrowser.open(url, 2)
        return result
    before = spotify_now_playing()
    try:
        os.startfile(item["uri"] if item else f"spotify:search:{quote(query)}")  # type: ignore[attr-defined]  # noqa: S606
    except OSError:
        logger.warning("O app do Spotify não abriu o link; usando o Spotify Web.", exc_info=True)
        webbrowser.open(url, 2)
        return result
    if item is None:
        return {**result, "state": "search"}

    wait = SPOTIFY_COLD_START_SECONDS if before is None else SPOTIFY_START_SECONDS
    now = _wait_for_spotify(item, query, before, wait)
    if _spotify_confirms(now, item, query, before):
        return {**result, "state": "playing", "now": now}

    window = _spotify_window() if now == "" and item["kind"] in {"track", "album"} else None
    if window is not None:
        # Abriu pausado: dá play só na janela do Spotify (a tecla de mídia global poderia ir para outra aba).
        win_desktop.send_app_command(window.hwnd, win_desktop.APPCOMMAND_MEDIA_PLAY_PAUSE)
        now = _wait_for_spotify(item, query, "", SPOTIFY_PLAY_SECONDS, stop_on_any=True)
        if _spotify_confirms(now, item, query, ""):
            return {**result, "state": "playing", "now": now}
        if now:
            # Retomou a fila antiga em vez do pedido: pausa de novo para não deixar a música errada tocando.
            win_desktop.send_app_command(window.hwnd, win_desktop.APPCOMMAND_MEDIA_PLAY_PAUSE)
            now = ""
    return {**result, "state": "opened" if now is not None else "unverified", "now": now}


def describe_spotify(result: dict[str, Any], query: str) -> str:
    item = result["item"]
    if item:
        artist = f" de {item['artist']}" if item["artist"] and item["kind"] in {"track", "album"} else ""
        what = f"{SPOTIFY_KIND_LABELS[item['kind']]} '{item['name']}'{artist}"
    else:
        what = f"'{query}'"
    state = result["state"]
    if state == "playing":
        return f"Tocando agora no app do Spotify: '{result['now']}' (confirmado pelo título da janela do Spotify)."
    if state == "opened":
        still = f": ele continua tocando '{result['now']}'" if result["now"] else ""
        return (
            f"Abri {what} no app do Spotify, mas não consegui confirmar que começou a tocar{still}. "
            "Diga isso ao usuário (ele pode apertar play no Spotify). Não diga que está tocando."
        )
    if state == "unverified":
        return (
            f"Pedi ao app do Spotify para abrir {what}, mas não consegui ler o que ele está tocando. "
            "Não afirme que está tocando."
        )
    if state == "search":
        return (
            f"Não achei um link exato; abri só a busca por '{query}' no app do Spotify. Nada começou a tocar: "
            "o usuário precisa escolher um resultado."
        )
    return (
        f"Abri {what} no Spotify Web, no navegador (o app do Spotify não está disponível). O navegador não "
        "começa a tocar sozinho: o usuário precisa apertar play. Não diga que está tocando."
    )


def streaming_url(service: str, query: str | None) -> tuple[str, str, bool]:
    key = normalize(service)
    key = STREAMING_ALIASES.get(key, key)
    if key not in STREAMING_SERVICES:
        names = ", ".join(info[0] for info in STREAMING_SERVICES.values())
        raise PCControlError(f"Não conheço esse serviço. Disponíveis: {names}.")
    label, home, template = STREAMING_SERVICES[key]
    if query and template:
        return label, template.format(q=quote_plus(query), path=quote(query)), True
    return label, home, False


def screenshot_to_pictures() -> Path:
    import pyautogui

    folder = resolve_folder("imagens") / "Jarvis"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"jarvis-{dt.datetime.now():%Y%m%d-%H%M%S}.png"
    pyautogui.screenshot().save(path)
    return path


# ───────────────────────── tools ─────────────────────────


async def _run(name: str, detail: str | None, func: Any, *args: Any) -> Any:
    await tool_status(name, "running", detail)
    try:
        result = await asyncio.to_thread(func, *args)
    except PCControlError:
        await tool_status(name, "error", detail)
        raise
    except Exception as exc:
        logger.exception("Falha na ação '%s'.", name)
        await tool_status(name, "error", detail)
        raise PCControlError("Algo deu errado ao executar essa ação no computador.") from exc
    await tool_status(name, "done", detail)
    return result


@function_tool()
async def open_website(context: RunContext, url: str, monitor: int | None = None) -> str:
    """Open a website in the user's default browser (new tab, or its own window on a monitor).

    Args:
        url: A full URL, a domain ("github.com"), a well-known service name ("Google Maps",
            "Gmail", "Claude", "ChatGPT") or one of the user's saved shortcuts.
            Never invent URLs: if unsure, search_web first and pass the official result URL.
        monitor: Monitor number (tela 1, 2, 3) when the user says where to open it
            ("abre o YouTube no monitor 1"). The site then opens in a new browser window that is
            moved there, so the HUD's window stays put. Don't call manage_window afterwards.
    """
    try:
        label, target = resolve_site(url)
        await net_activity([host_of(target)], "request")
        result = await _run("open_website", label, open_url, label, target, monitor)
        logger.info("Site aberto: %s %s", target, f"(tela {monitor})" if monitor else "")
        return result
    except PCControlError as exc:
        return str(exc)


@function_tool()
async def save_shortcut(context: RunContext, name: str, url: str) -> str:
    """Save a personal website shortcut so it can be opened by name later.

    Args:
        name: How the user calls it, e.g. "portal SATC".
        url: The exact http(s) URL.
    """
    try:
        label, target = await asyncio.to_thread(save_shortcut_entry, name, url)
    except PCControlError as exc:
        return str(exc)
    logger.info("Atalho salvo: %s -> %s", label, target)
    return f"Atalho '{label}' salvo para {host_of(target)}."


@function_tool()
async def manage_window(
    context: RunContext,
    target: str,
    action: Literal["move", "back", "maximize", "minimize", "restore", "focus", "snap_left", "snap_right", "close"],
    monitor: int | None = None,
) -> str:
    """Move, maximize, minimize, focus, snap or close an application window, across monitors.

    The result says the monitor the window really ended up on: report that one.

    Args:
        target: App name or text from the window title, e.g. "Configurações", "Edge", "WhatsApp".
        action: move (to another monitor; needs `monitor`), back (undo the last move/maximize/snap
            and put the window where it was before — "volta pra antiga", "desfaz"), maximize,
            minimize, restore, focus, snap_left, snap_right or close (polite close of that single window).
        monitor: Monitor number as Windows numbers them (tela 1, 2, 3) for move/maximize.
            Never guess it for "back".
    """
    try:
        result = await _run("manage_window", target, window_action, target, action, monitor)
        logger.info("Janela: %s %s %s", action, target, monitor or "")
        return result
    except PCControlError as exc:
        return str(exc)


@function_tool()
async def look_at_screen(context: RunContext, monitor: int | None = None, window: str | None = None) -> str:
    """Look at what is on the user's screen. Only when the user explicitly asks to see/read the screen.

    Takes a screenshot, shows it on the HUD and sends it to you as an image so you can
    read and describe it. Prefer `window` when the user names an app (sharper image).

    Args:
        monitor: Monitor number (tela 1, 2, 3). Omit both arguments to capture every monitor.
        window: App or window title to capture alone, e.g. "PhpStorm", "Edge", "WhatsApp".
    """
    detail = window or (f"tela {monitor}" if monitor else "todas as telas")
    try:
        image, label = await _run("look_at_screen", detail, capture_screen, monitor, window)
    except PCControlError as exc:
        return str(exc)

    sent_to_model = push_image_to_model(context, image)
    await send_screenshot(image, label)
    logger.info("Captura (%s) enviada para análise.", label)
    if not sent_to_model:
        return "Tirei o print e mostrei no HUD, mas este modelo não recebe imagens; não consigo lê-lo."
    return (
        f"Print ({label}) capturado, exibido no HUD e enviado a você como imagem. "
        "Descreva o que vê respondendo ao pedido do usuário. Nunca leia senhas, chaves ou tokens em voz alta."
    )


def play_video(query: str, monitor: int | None, live: bool = False) -> tuple[dict[str, str] | None, str]:
    """Open the best YouTube match, optionally in its own window on `monitor`.

    Returns (None, "") when nothing matches, so play_youtube decides between the live
    fallback (Twitch) and opening the search page.
    """
    if monitor is not None:
        pick_monitor(monitor)  # tela inexistente falha antes de abrir qualquer coisa
    video = find_youtube_video(query, live)
    if video is None:
        return None, ""
    channel = f" do canal {video['channel']}" if video["channel"] else ""
    if monitor is None:
        webbrowser.open(video["url"], 2)
        return video, f"Abri no YouTube: '{video['title']}'{channel}."
    return video, open_in_new_window(f"'{video['title']}'{channel} no YouTube", video["url"], monitor)


@function_tool()
async def play_youtube(
    context: RunContext, query: str, live: bool = False, monitor: int | None = None
) -> str:
    """Search YouTube and open the best matching video or live stream in the browser.

    The result gives the real title and channel and says whether it is live right now.
    Opening a page is not confirmed playback: repeat what the result says.

    Args:
        query: What or who to watch, e.g. "lo-fi para estudar", "trailer Homem de Ferro" or "Gaules".
        live: True when the user asks for a live stream ("a live do…", "ao vivo"). Then only a
            stream that is live right now is opened; if there is none, nothing is opened and the
            result says what to offer instead (e.g. the Twitch channel).
        monitor: Monitor number (tela 1, 2, 3) when the user says where to play it; the video
            opens in its own browser window moved there.
    """
    live = live or wants_live(query)
    await net_activity(["youtube.com"], "request")
    try:
        video, placement = await _run("play_youtube", query, play_video, query, monitor, live)
    except PCControlError as exc:
        return str(exc)

    if video is None and live:
        subject = live_subject(query)
        await net_activity(["twitch.tv"], "request")
        channel = await asyncio.to_thread(lookup_twitch_channel, subject)
        message = f"Não encontrei uma live de '{subject}' acontecendo agora no YouTube, então não abri nada."
        if channel:
            message += f" Conferi a Twitch: {twitch_summary(channel)}."
            if channel["live"] and not channel["rerun"]:
                message += f" Ofereça abrir com open_streaming('Twitch', '{channel['login']}')."
        else:
            message += f" Ofereça procurar na Twitch com open_streaming('Twitch', {json.dumps(subject, ensure_ascii=False)})."
        return message + " Não diga que está tocando."

    if video is None:
        url = STREAMING_SERVICES["youtube"][2].format(q=quote_plus(query), path=quote(query))  # type: ignore[union-attr]
        try:
            opened = await asyncio.to_thread(open_url, f"a busca do YouTube por '{query}'", url, monitor)
        except PCControlError as exc:
            return str(exc)
        remember_media("YouTube", "YouTube", url)
        return f"Não achei um vídeo exato. {opened} Só a busca está aberta: nada está tocando ainda."

    remember_media("YouTube", video["title"], video["url"])
    channel_label = video["channel"] + (" · AO VIVO" if video.get("status") == "live" else "")
    await show_card(
        "media",
        {
            "service": "YouTube",
            "title": video["title"],
            "url": video["url"],
            "channel": channel_label,
            "thumbnail": video["thumbnail"],
        },
    )
    logger.info("YouTube aberto (%s): %s", video.get("status"), video["url"])
    summary = describe_youtube(video)
    return summary if monitor is None else f"{summary} Janela: {placement}"


async def _open_spotify(query: str) -> str:
    await net_activity(["duckduckgo.com", "open.spotify.com"], "request")
    try:
        result = await _run("open_streaming", f"Spotify: {query}", play_spotify, query)
    except PCControlError as exc:
        return str(exc)
    item = result["item"]
    in_browser = result["state"] == "web"
    remember_media("Spotify", "Spotify", result["url"], where="browser" if in_browser else "app")
    status = {
        "playing": "Tocando no app do Spotify",
        "opened": "Aberto no app, sem reprodução confirmada",
        "unverified": "Aberto no app, sem reprodução confirmada",
        "search": "Só a busca foi aberta",
        "web": "Spotify Web: aperte play",
    }[result["state"]]
    title = result["now"] if result["state"] == "playing" else (item["name"] if item else query)
    await show_card("media", {"service": "Spotify", "title": title, "url": result["url"], "channel": status, "thumbnail": ""})
    logger.info("Spotify (%s): %s", result["state"], item["uri"] if item else query)
    return describe_spotify(result, query)


async def _open_twitch(query: str) -> str:
    await net_activity(["twitch.tv"], "request")
    try:
        result = await _run("open_streaming", f"Twitch: {query}", open_twitch, query)
    except PCControlError as exc:
        return str(exc)
    channel = result["channel"]
    remember_media("Twitch", channel["name"] if channel else "Twitch", result["url"])
    if channel:
        status = "AO VIVO" if channel["live"] and not channel["rerun"] else ("Reprise" if channel["live"] else "Offline")
        card = {"title": channel["title"] or channel["name"], "channel": f"{channel['name']} · {status}"}
    else:
        card = {"title": query, "channel": "Busca da Twitch"}
    await show_card("media", {"service": "Twitch", "url": result["url"], "thumbnail": "", **card})
    return describe_twitch(result, query)


@function_tool()
async def open_streaming(
    context: RunContext, service: str, query: str | None = None, monitor: int | None = None
) -> str:
    """Open a streaming/music service, optionally with something to find or play.

    - Spotify + query: tries to really play it in the Spotify desktop app and says whether
      playback was confirmed (otherwise it says it only opened the item or the search).
    - Twitch + query (a channel name): opens that channel and says if it is live, a rerun or offline.
    - Other services only open their search page: nothing starts playing by itself.

    Args:
        service: Netflix, Prime Video, Spotify, Twitch, Globoplay, Disney+, Max, Crunchyroll, Deezer or YouTube.
        query: Optional title, artist, song, show or channel.
        monitor: Monitor number (tela 1, 2, 3) when the user says where to open it; the service
            opens in its own browser window moved there (not for the Spotify app).
    """
    try:
        label, url, searched = streaming_url(service, query)
    except PCControlError as exc:
        return str(exc)
    not_moved = (
        f" (Não mudei para a tela {monitor}: isso só vale para sites abertos numa janela nova.)" if monitor else ""
    )
    if label == "Spotify" and query:
        return await _open_spotify(query) + not_moved
    if label == "Twitch" and query:
        return await _open_twitch(query) + not_moved

    try:
        await net_activity([host_of(url)], "request")
        what = f"o {label}" + (f" buscando '{query}'" if query and searched else "")
        if monitor is None:
            await _run("open_streaming", label, webbrowser.open, url, 2)
            result = f"Abri {what}."
        else:
            result = await _run("open_streaming", label, open_in_new_window, what, url, monitor)
    except PCControlError as exc:
        return str(exc)
    remember_media(label, label, url)
    await show_card("media", {"service": label, "title": query or label, "url": url, "channel": "", "thumbnail": ""})
    if query and not searched:
        return f"{result} A busca direta não é suportada nele, então procure '{query}' por lá. Nada está tocando."
    if query:
        return f"{result} Só mostra os resultados da busca: nada está tocando até o usuário escolher."
    return result


@function_tool()
async def open_app(context: RunContext, name: str, monitor: int | None = None) -> str:
    """Open an installed application by name (any app in the Start Menu) and bring its window to the front.

    It checks that a visible window really appeared; report exactly what the result says
    (it may say the app is hidden in the tray or did not open). Never opens installers or uninstallers.

    Args:
        name: App name, e.g. "Spotify", "calculadora", "VS Code", "WhatsApp", "Steam".
        monitor: Monitor number (tela 1, 2, 3) when the user says where to open it.
    """
    try:
        result = await _run("open_app", name, launch_app, name, monitor)
        logger.info("App aberto: %s → %s", name, result)
        return result
    except PCControlError as exc:
        return str(exc)


@function_tool()
async def close_app(context: RunContext, name: str) -> str:
    """Close an open application gracefully (like clicking the X).

    It waits for the process to really exit; if the result says it is still running
    (tray, unsaved work), tell the user that instead of saying it closed.
    System processes and Jarvis itself are protected.

    Args:
        name: App name, e.g. "Spotify", "Discord", "bloco de notas".
    """
    try:
        result = await _run("close_app", name, close_app_processes, name)
        logger.info("Fechar app %s → %s", name, result)
        return result
    except PCControlError as exc:
        return str(exc)


@function_tool()
async def browser_tab(
    context: RunContext,
    action: Literal["new", "close", "next", "previous", "reopen", "switch"],
    name: str | None = None,
) -> str:
    """Control tabs of the open web browser (Edge, Chrome...), only for websites.

    The panels of the Jarvis HUD ("abas"/"abinhas" on the screen, on the left, Reprodução,
    Leitura de tela, Timer...) are NOT browser tabs: use manage_hud_panels for them.

    To close a video, live or music Jarvis opened ("fecha a aba de reprodução", "fecha o vídeo"),
    use action="close" with the title the media tool reported, or just name="reprodução":
    the last opened media is found by its exact title. Closing is never pausing.

    Args:
        action: new (open a new tab), close, next, previous, reopen (last closed tab) or switch.
        name: Text from the tab title for close/switch, e.g. "YouTube" or "Tudo Gostoso".
            Required for close.
    """
    if action == "close" and not (name or "").strip():
        return (
            "NADA foi fechado: para fechar uma aba do navegador diga o site (ex.: 'YouTube'). "
            "Se o usuário falou de uma aba/painel do HUD, use manage_hud_panels."
        )
    try:
        result = await _run("browser_tab", name or action, browser_tab_action, action, name)
        logger.info("Aba do navegador: %s %s", action, name or "")
        return result
    except PCControlError as exc:
        return str(exc)


@function_tool()
async def media_control(
    context: RunContext,
    action: Literal["play_pause", "next", "previous", "stop"],
) -> str:
    """Pause/resume or skip whatever media is playing (YouTube, Spotify, Netflix…) with the media keys.

    This never closes anything. To close a video, live or music Jarvis opened, use
    browser_tab(action="close", name=<its title>); for an app (e.g. Spotify) use close_app.

    Never use it to close anything: closing the HUD's Reprodução panel is manage_hud_panels.

    Args:
        action: play_pause (toggles), next, previous or stop.
    """
    try:
        await _run("media_control", action, press_media_key, action)
        return (
            f"Tecla de mídia '{action}' enviada. Ela só pausa, retoma ou pula: não fecha nada, e não sei "
            "se a mídia ficou tocando ou pausada."
        )
    except PCControlError as exc:
        return str(exc)


@function_tool()
async def set_volume(
    context: RunContext,
    action: Literal["set", "up", "down", "mute", "unmute"],
    level: int | None = None,
) -> str:
    """Change the computer's master volume.

    Args:
        action: set (to an exact level), up, down, mute or unmute.
        level: 0-100 for "set"; optional step for up/down (default 10).
    """
    try:
        value = await _run("set_volume", action, change_volume, action, level)
    except PCControlError as exc:
        return str(exc)
    if action == "mute":
        return "Som silenciado."
    if action == "unmute":
        return f"Som reativado em {value}%."
    return f"Volume em {value}%."


@function_tool()
async def open_folder(context: RunContext, folder: str) -> str:
    """Open a personal folder in the file explorer.

    Args:
        folder: Downloads, Documentos, Área de trabalho, Imagens, Músicas or Vídeos.
    """
    try:
        path = await asyncio.to_thread(resolve_folder, folder)
        await _run("open_folder", path.name, open_path, path)
        return f"Abri a pasta {path.name}."
    except PCControlError as exc:
        return str(exc)


@function_tool()
async def lock_computer(context: RunContext) -> str:
    """Lock the computer screen (the user will need their password to come back)."""
    if not IS_WINDOWS:
        return "Bloquear a tela só está disponível no Windows por enquanto."
    import ctypes

    await tool_status("lock_computer", "running")
    ctypes.windll.user32.LockWorkStation()
    await tool_status("lock_computer", "done")
    logger.info("Tela bloqueada a pedido do usuário.")
    return "Tela bloqueada."


@function_tool()
async def take_screenshot(context: RunContext) -> str:
    """Take a screenshot and save it to the Pictures/Jarvis folder."""
    try:
        path = await _run("take_screenshot", None, screenshot_to_pictures)
        logger.info("Captura salva em %s", path)
        return f"Captura salva em Imagens/Jarvis como {path.name}."
    except PCControlError as exc:
        return str(exc)


def build_pc_tools() -> list[Any]:
    return [
        open_website,
        play_youtube,
        open_streaming,
        open_app,
        close_app,
        browser_tab,
        media_control,
        set_volume,
        open_folder,
        lock_computer,
        take_screenshot,
        manage_window,
        look_at_screen,
        save_shortcut,
    ]
