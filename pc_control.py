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
MAX_REMEMBERED_WINDOWS = 60

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
LAYOUTS_FILE = Path(__file__).resolve().parent / "layouts.json"

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
class Batch:
    """Windows moved/minimized together (layout, 'organiza tudo', área de trabalho), to undo at once."""

    label: str
    moves: list[tuple[int, SavedPosition]]  # (hwnd, onde estava), na ordem Z de antes


@dataclass
class WindowMemory:
    """What Jarvis remembers about windows while it runs (keys are hwnds)."""

    positions: dict[int, list[SavedPosition]] = field(default_factory=dict)  # antes de cada move, para 'back'
    labels: dict[int, set[str]] = field(default_factory=dict)  # janelas que o Jarvis abriu → nomes pedidos
    hud_windows: set[int] = field(default_factory=set)  # janelas de navegador onde o HUD já apareceu
    batch: Batch | None = None  # a última ação em lote, para desfazer tudo de uma vez


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


def launch_app(name: str, monitor: int | str | None = None) -> str:
    """Open an app, confirm a visible window appeared and bring it to the front (or to `monitor`)."""
    _require_windows("Abrir apps")
    screen = pick_monitor(monitor) if _screen_ref(monitor) is not None else None
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
    where = f" {_on_screen(landed)}" if landed else ""
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


def _screen_ref(monitor: int | str | None) -> int | str | None:
    """None when no screen was asked for (models sometimes send an empty string)."""
    if monitor is None or (isinstance(monitor, str) and not monitor.strip()):
        return None
    return monitor


def pick_monitor(monitor: int | str | None) -> win_desktop.Monitor:
    """The screen the user named: number as in the Windows Settings ("1", "tela 3"), name or nickname."""
    screens = win_desktop.monitors()
    if not screens:
        raise PCControlError("Não consegui ler os monitores.")
    if _screen_ref(monitor) is None:
        return next((m for m in screens if m.primary), screens[0])
    try:
        return win_desktop.find_monitor(monitor, screens)  # type: ignore[arg-type]
    except ValueError as exc:
        raise PCControlError(str(exc)) from None


def _on_screen(screen: win_desktop.Monitor) -> str:
    """'no monitor de cima (tela 3)', 'no notebook (tela 1)' or 'na tela 2'."""
    return f"{'no' if screen.name else 'na'} {screen.label}"


def _to_screen(screen: win_desktop.Monitor) -> str:
    """'para o notebook (tela 1)' or 'para a tela 2'."""
    return f"para {'o' if screen.name else 'a'} {screen.label}"


def _screen_numbered(number: int | None) -> win_desktop.Monitor | None:
    return next((m for m in win_desktop.monitors() if m.number == number), None) if number is not None else None


def _remember_position(hwnd: int) -> SavedPosition | None:
    """Save where the window is before Jarvis moves it, so 'back' can undo the move."""
    placement = win_desktop.get_placement(hwnd)
    if placement is None:
        return None
    screen = win_desktop.window_monitor(hwnd) or win_desktop.monitor_for_rect(placement.normal, win_desktop.monitors())
    saved = SavedPosition(placement, screen.number if screen else None)
    stack = MEMORY.positions.pop(hwnd, [])  # reinserir deixa a janela movida por último no fim
    MEMORY.positions[hwnd] = [*stack, saved][-MAX_SAVED_POSITIONS:]
    while len(MEMORY.positions) > MAX_REMEMBERED_WINDOWS:
        MEMORY.positions.pop(next(iter(MEMORY.positions)))
    return saved


def _hud_note(hwnd: int) -> str:
    if hwnd in MEMORY.hud_windows:
        return " O HUD do Jarvis está numa aba dessa mesma janela e foi junto."
    return ""


def _landed(hwnd: int, title: str, wanted: int | None, verb: str) -> tuple[win_desktop.Monitor | None, str]:
    """(monitor the window really is on, problem to report) — never trust the monitor we only asked for."""
    screen = win_desktop.window_monitor(hwnd)
    if screen is None:
        return None, f"Tentei {verb} '{title}', mas não consegui confirmar em que tela ela ficou."
    if wanted is not None and screen.number != wanted:
        target = _screen_numbered(wanted)
        to = _to_screen(target) if target else f"para a tela {wanted}"
        return screen, f"Tentei {verb} '{title}' {to}, mas ela ficou {_on_screen(screen)}."
    return screen, ""


def _move_window(window: win_desktop.Window, screen: win_desktop.Monitor, maximize: bool | None = None) -> str:
    _remember_position(window.hwnd)
    win_desktop.move_to_monitor(window.hwnd, screen, maximize=maximize)
    title = _clean_title(window.title)
    landed, problem = _landed(window.hwnd, title, screen.number, "levar")
    if problem or landed is None:
        return problem
    state = " e maximizada" if maximize else ""
    return f"'{title}' agora está {_on_screen(landed)}{state}.{_hud_note(window.hwnd)}"


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
    landed, problem = _landed(window.hwnd, title, saved.monitor, "devolver")
    if problem or landed is None:
        return problem
    state = ", maximizada" if saved.placement.maximized else ""
    return f"'{title}' voltou para onde estava: {landed.label}{state}.{_hud_note(window.hwnd)}"


def window_action(target: str, action: str, monitor: int | str | None) -> str:
    _require_windows("Controlar janelas")
    if action == "back":
        return _move_back(target)
    window = find_window(target, wait=FIND_WINDOW_SECONDS)
    protected = PROTECTED_PROCESSES | _jarvis_ancestor_names()

    monitor = _screen_ref(monitor)
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
        where = f" {_on_screen(screen)}" if screen else ""
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


# ───────────────────────── screens & layouts ─────────────────────────

MAX_NICKNAME_CHARS = 40
MAX_LISTED = 5
FRAME_HOSTS = {"applicationframehost.exe"}  # apps da Microsoft Store: o app é o título, não o processo
NO_RELAUNCH = {"explorer.exe"}  # pastas abertas não voltam pelo nome do processo
LAUNCH_NAMES = {"windowsterminal.exe": "terminal"}
FRAME_HOST_MIN_SIMILARITY = 0.6
LAYOUT_FILLER = {"o", "a", "meu", "minha", "modo", "layout", "perfil", "organizacao", "de", "do", "da"}
UNDO_HINT = "Se o usuário pedir para desfazer, use arrange_windows(action='undo')."


def _short_title(title: str, limit: int = 40) -> str:
    text = _clean_title(title)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _names(items: list[str]) -> str:
    shown = ", ".join(f"'{item}'" for item in items[:MAX_LISTED])
    return shown + (f" e mais {len(items) - MAX_LISTED}" if len(items) > MAX_LISTED else "")


def _screen_title(screen: win_desktop.Monitor) -> str:
    """'notebook', 'monitor vertical' or, without a name, the model/size."""
    if screen.name:
        return screen.label.removesuffix(f" (tela {screen.number})")
    return screen.model or f"{screen.width}x{screen.height}"


def _numbering(screens: list[win_desktop.Monitor]) -> str:
    return ", ".join(f"tela {m.number} = {_screen_title(m)}" for m in screens)


def screens_overview() -> str:
    screens = win_desktop.monitors()
    if not screens:
        raise PCControlError("Não consegui ler os monitores.")
    if all(m.confirmed for m in screens):
        status = "Numeração confirmada pelo usuário."
    else:
        status = (
            "Numeração estimada para bater com o 'Identificar' das Configurações do Windows (Sistema > Tela); "
            "se algum número estiver diferente, o usuário diz qual tela é qual (ex.: 'a tela 1 é o notebook')."
        )
    return f"{win_desktop.describe_monitors(screens)}. {status}"


def _screen_entry(config: dict[str, dict[str, Any]], screen: win_desktop.Monitor) -> dict[str, Any]:
    if not screen.hardware_id:
        raise PCControlError("Não consegui identificar o hardware dessa tela para guardar a configuração.")
    entry = config.setdefault(screen.hardware_id, {})
    kind = screen.model or ("tela do notebook" if screen.internal else "monitor")
    entry["monitor"] = f"{kind} {screen.width}x{screen.height}"
    return entry


def nickname_screen(reference: int | str | None, nickname: str | None) -> str:
    label = re.sub(r"\s+", " ", (nickname or "").strip()).strip("'\" .")
    if not label or len(label) > MAX_NICKNAME_CHARS:
        raise PCControlError("Diga um apelido curto para a tela.")
    if re.fullmatch(r"(?:tela|monitor)?\s*\d+", normalize(label)):
        raise PCControlError("Use um nome como apelido, não um número: os números são os das Configurações.")
    if _screen_ref(reference) is None:
        raise PCControlError("Diga qual tela vai ganhar o apelido (número ou nome).")
    screen = pick_monitor(reference)
    try:
        other = win_desktop.find_monitor(label, win_desktop.monitors())
    except ValueError:
        other = None
    if other is not None and other.hardware_id != screen.hardware_id:
        raise PCControlError(f"'{label}' já indica o {other.label}. Escolha outro apelido.")
    config = win_desktop.load_screen_config()
    entry = _screen_entry(config, screen)
    names = [name for name in entry.get("apelidos", []) if normalize(str(name)) != normalize(label)]
    entry["apelidos"] = [*names, label]
    win_desktop.save_screen_config(config)
    return f"Pronto: o {screen.label} agora também atende por '{label}'."


def forget_screen_nickname(nickname: str | None) -> str:
    wanted = normalize(nickname or "")
    if not wanted:
        raise PCControlError("Diga qual apelido devo esquecer.")
    config = win_desktop.load_screen_config()
    found = False
    for entry in config.values():
        names = entry.get("apelidos", [])
        keep = [name for name in names if normalize(str(name)) != wanted]
        if len(keep) != len(names):
            entry["apelidos"] = keep
            found = True
    if not found:
        raise PCControlError(f"Nenhuma tela tem o apelido '{nickname}'.")
    win_desktop.save_screen_config(config)
    return f"Esqueci o apelido '{nickname}'."


def _save_numbers(screens: list[win_desktop.Monitor], numbers: dict[str, int]) -> None:
    config = win_desktop.load_screen_config()
    for screen in screens:
        _screen_entry(config, screen)["numero"] = numbers[screen.hardware_id]
    win_desktop.save_screen_config(config)


def renumber_screen(reference: int | str | None, number: int | None) -> str:
    """The user says which number the Settings app shows on a screen; the screen that had it swaps."""
    screens = win_desktop.monitors()
    if _screen_ref(reference) is None or number is None:
        raise PCControlError("Diga qual tela e qual número o 'Identificar' das Configurações mostra nela.")
    screen = pick_monitor(reference)
    if not 1 <= number <= len(screens):
        raise PCControlError(f"Só existem {len(screens)} telas: o número vai de 1 a {len(screens)}.")
    if any(not m.hardware_id for m in screens):
        raise PCControlError("Não consegui identificar o hardware das telas para guardar a numeração.")
    numbers = {m.hardware_id: m.number for m in screens}
    other = next(m for m in screens if m.number == number)
    numbers[other.hardware_id], numbers[screen.hardware_id] = screen.number, number
    _save_numbers(screens, numbers)
    return f"Anotado, como no 'Identificar' das Configurações: {_numbering(win_desktop.monitors())}."


def confirm_screens() -> str:
    screens = win_desktop.monitors()
    if not screens:
        raise PCControlError("Não consegui ler os monitores.")
    if any(not m.hardware_id for m in screens):
        raise PCControlError("Não consegui identificar o hardware das telas para guardar a numeração.")
    _save_numbers(screens, {m.hardware_id: m.number for m in screens})
    return f"Numeração confirmada e guardada: {_numbering(screens)}."


def screens_action(
    action: str, screen: int | str | None = None, name: str | None = None, number: int | None = None
) -> str:
    if action == "list":
        return screens_overview()
    if action == "nickname":
        return nickname_screen(screen, name)
    if action == "forget_nickname":
        return forget_screen_nickname(name)
    if action == "renumber":
        return renumber_screen(screen, number)
    if action == "confirm":
        return confirm_screens()
    raise PCControlError(f"Ação de telas desconhecida: {action}.")


PlacedWindow = tuple[win_desktop.Window, win_desktop.Placement, win_desktop.Monitor]


def _is_hud_window(window: win_desktop.Window) -> bool:
    return HUD_TITLE in window.title or window.hwnd in MEMORY.hud_windows


def _placed_windows() -> list[PlacedWindow]:
    """Visible, non-minimized windows with their placement and monitor, in Z order (top first)."""
    screens = win_desktop.monitors()
    found = []
    for window in _desktop_windows():
        placement = win_desktop.get_placement(window.hwnd)
        if placement is None or placement.show_cmd == win_desktop.SW_SHOWMINIMIZED:
            continue
        screen = win_desktop.window_monitor(window.hwnd) or win_desktop.monitor_for_rect(placement.normal, screens)
        if screen is not None:
            found.append((window, placement, screen))
    return found


def _move_all(items: list[PlacedWindow], target: win_desktop.Monitor, label: str) -> str:
    hud = [window for window, _, screen in items if _is_hud_window(window) and screen.number != target.number]
    moves: list[tuple[int, SavedPosition]] = []
    moved: list[str] = []
    stuck: list[str] = []
    for window, _placement, screen in items:
        if screen.number == target.number or _is_hud_window(window):
            continue
        saved = _remember_position(window.hwnd)
        win_desktop.move_to_monitor(window.hwnd, target, focus=False)
        if saved is not None:
            moves.append((window.hwnd, saved))
        landed = win_desktop.window_monitor(window.hwnd)
        ok = landed is not None and landed.number == target.number
        (moved if ok else stuck).append(_short_title(window.title))
    if moves:
        MEMORY.batch = Batch(label, moves)
    parts = []
    if moved:
        parts.append(f"Levei {_count(len(moved), 'janela')} {_to_screen(target)}: {_names(moved)}.")
    if stuck:
        parts.append(f"{_names(stuck)} não {'saiu' if len(stuck) == 1 else 'saíram'} do lugar.")
    if not moved and not stuck:
        parts.append(f"Nenhuma janela para levar: as que estão abertas já estavam {_on_screen(target)}.")
    if hud:
        parts.append("A janela do HUD ficou onde estava.")
    if moves:
        parts.append(UNDO_HINT)
    return " ".join(parts)


def gather_windows(monitor: int | str | None) -> str:
    if _screen_ref(monitor) is None:
        raise PCControlError("Diga para qual tela devo levar todas as janelas.")
    target = pick_monitor(monitor)
    return _move_all(_placed_windows(), target, f"juntar tudo {_on_screen(target)}")


def move_screen_windows(from_monitor: int | str | None, monitor: int | str | None) -> str:
    if _screen_ref(from_monitor) is None or _screen_ref(monitor) is None:
        raise PCControlError("Diga de qual tela e para qual tela devo levar as janelas.")
    source, target = pick_monitor(from_monitor), pick_monitor(monitor)
    if source.number == target.number:
        raise PCControlError(f"A origem e o destino são a mesma tela ({source.label}).")
    items = [item for item in _placed_windows() if item[2].number == source.number]
    if not items:
        return f"Não há janelas abertas {_on_screen(source)}."
    return _move_all(items, target, f"levar tudo do {source.label} {_to_screen(target)}")


def show_desktop() -> str:
    items = _placed_windows()
    hud = any(_is_hud_window(window) for window, _, _ in items)
    targets = [window for window, _, _ in items if not _is_hud_window(window)]
    if not targets:
        return "Não há janelas abertas para minimizar: a área de trabalho já está à mostra."
    moves: list[tuple[int, SavedPosition]] = []
    for window in targets:
        saved = _remember_position(window.hwnd)
        win_desktop.show_window(window.hwnd, win_desktop.SW_MINIMIZE)
        if saved is not None:
            moves.append((window.hwnd, saved))
    MEMORY.batch = Batch("mostrar a área de trabalho", moves)
    still = []
    for window in targets:
        placement = win_desktop.get_placement(window.hwnd)
        if placement is not None and placement.show_cmd != win_desktop.SW_SHOWMINIMIZED:
            still.append(_short_title(window.title))
    done = len(targets) - len(still)
    message = f"Minimizei {_count(done, 'janela')}; a área de trabalho está à mostra."
    if still:
        message = f"Minimizei {_count(done, 'janela')}, mas {_names(still)} continua{'m' if len(still) > 1 else ''} aberta{'s' if len(still) > 1 else ''}."
    if hud:
        message += " A janela do HUD ficou aberta."
    return f"{message} Para trazer tudo de volta, use arrange_windows(action='undo')."


def undo_batch() -> str:
    batch = MEMORY.batch
    if batch is None:
        raise PCControlError(
            "Não tenho nenhuma ação em lote para desfazer. Para uma janela só, use manage_window com action 'back'."
        )
    present = {window.hwnd: window for window in _desktop_windows()}
    first = next((hwnd for hwnd, _ in batch.moves if hwnd in present), None)  # estava no topo: fica em foco
    back: list[str] = []
    stuck: list[str] = []
    gone = 0
    for hwnd, saved in reversed(batch.moves):  # de baixo para cima, para a ordem das janelas voltar igual
        window = present.get(hwnd)
        if window is None:
            gone += 1
            continue
        if not any(entry is saved for entry in MEMORY.positions.get(hwnd, [])):
            continue  # já voltou sozinha (manage_window 'back')
        stack = [entry for entry in MEMORY.positions.get(hwnd, []) if entry is not saved]
        if stack:
            MEMORY.positions[hwnd] = stack
        else:
            MEMORY.positions.pop(hwnd, None)
        win_desktop.restore_placement(hwnd, saved.placement, focus=hwnd == first)
        landed = win_desktop.window_monitor(hwnd)
        ok = saved.monitor is None or (landed is not None and landed.number == saved.monitor)
        (back if ok else stuck).append(_short_title(window.title))
    MEMORY.batch = None
    parts = [f"Desfiz '{batch.label}': {_count(len(back), 'janela')} de volta onde estava{'m' if len(back) != 1 else ''}."]
    if stuck:
        parts.append(f"{_names(stuck)} não voltou para a tela de antes.")
    if gone:
        parts.append(f"{_count(gone, 'janela')} já tinha{'m' if gone > 1 else ''} sido fechada{'s' if gone > 1 else ''}.")
    return " ".join(parts)


def arrange_action(action: str, monitor: int | str | None = None, from_monitor: int | str | None = None) -> str:
    _require_windows("Organizar janelas")
    if action == "gather":
        return gather_windows(monitor)
    if action == "move_all":
        return move_screen_windows(from_monitor, monitor)
    if action == "show_desktop":
        return show_desktop()
    if action == "undo":
        return undo_batch()
    raise PCControlError(f"Ação de organização desconhecida: {action}.")


def _layout_label(name: str) -> str:
    words = name.strip().strip("'\".").split()
    while words and normalize(words[0]) in LAYOUT_FILLER:
        words.pop(0)
    return " ".join(words)


def _layout_key(name: str) -> str:
    return normalize(_layout_label(name))


def load_layouts() -> dict[str, dict[str, Any]]:
    """layouts.json: {nome: {"salvo_em": ..., "janelas": [{app, processo, titulo, tela, posicao...}]}}."""
    try:
        data = json.loads(LAYOUTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict) and isinstance(v.get("janelas"), list)}


def _write_layouts(layouts: dict[str, dict[str, Any]]) -> None:
    LAYOUTS_FILE.write_text(json.dumps(layouts, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_layout(name: str | None, layouts: dict[str, dict[str, Any]], fuzzy: bool = True) -> str:
    key = _layout_key(name or "")
    if not key:
        raise PCControlError("Diga o nome do layout.")
    by_key = {_layout_key(stored): stored for stored in layouts}
    if key in by_key:
        return by_key[key]
    match = best_match(key, list(by_key)) if fuzzy else None
    if match:
        return by_key[match]
    saved = ", ".join(f"'{stored}'" for stored in layouts) or "nenhum"
    raise PCControlError(f"Não tenho um layout chamado '{name}'. Salvos: {saved}.")


def _launch_name(window: win_desktop.Window) -> str:
    """Name launch_app understands for the window's app ('' when it can't be reopened by name)."""
    if window.process in NO_RELAUNCH:
        return ""
    if window.process in FRAME_HOSTS:
        return _clean_title(window.title)
    if window.process in LAUNCH_NAMES:
        return LAUNCH_NAMES[window.process]
    alias = next((name for name, exes in PROCESS_ALIASES.items() if window.process in exes), None)
    return alias or re.sub(r"\d+$", "", window.process.removesuffix(".exe"))


def _layout_entry(window: win_desktop.Window, placement: win_desktop.Placement, screen: win_desktop.Monitor,
                  offset: tuple[int, int]) -> dict[str, Any]:  # fmt: skip
    ox, oy = offset
    left, top, right, bottom = placement.normal
    wx, wy = screen.work[0], screen.work[1]
    return {
        "app": _launch_name(window),
        "processo": window.process,
        "titulo": _clean_title(window.title),
        "tela": screen.number,
        "tela_id": screen.hardware_id,
        "tela_nome": screen.name,
        "maximizada": placement.maximized,
        # Relativa à área de trabalho da tela: continua certa se os monitores mudarem de lugar.
        "posicao": [left + ox - wx, top + oy - wy, right + ox - wx, bottom + oy - wy],
    }


def _layout_screen(entry: dict[str, Any], screens: list[win_desktop.Monitor]) -> win_desktop.Monitor:
    """Same physical monitor if connected, else the one with the same name or number, else the primary."""
    for wanted, field_name in ((entry.get("tela_id"), "hardware_id"), (entry.get("tela_nome"), "name")):
        match = next((m for m in screens if wanted and getattr(m, field_name) == wanted), None)
        if match is not None:
            return match
    by_number = next((m for m in screens if m.number == entry.get("tela")), None)
    return by_number or next((m for m in screens if m.primary), screens[0])


def _layout_placement(entry: dict[str, Any], screen: win_desktop.Monitor, offset: tuple[int, int]) -> win_desktop.Placement:
    rel = entry.get("posicao") or [0, 0, 1200, 800]
    work_left, work_top, work_right, work_bottom = screen.work
    width = min(max(int(rel[2]) - int(rel[0]), 200), work_right - work_left)
    height = min(max(int(rel[3]) - int(rel[1]), 150), work_bottom - work_top)
    left = min(max(work_left + int(rel[0]), work_left), work_right - width)
    top = min(max(work_top + int(rel[1]), work_top), work_bottom - height)
    ox, oy = offset
    normal = (left - ox, top - oy, left + width - ox, top + height - oy)
    show = win_desktop.SW_MAXIMIZE if entry.get("maximizada") else win_desktop.SW_SHOWNORMAL
    return win_desktop.Placement(0, show, (-1, -1), (-1, -1), normal)


def _match_layout(entries: dict[int, dict[str, Any]], windows: list[win_desktop.Window], taken: set[int]
                  ) -> dict[int, win_desktop.Window]:  # fmt: skip
    """Pair saved entries with open windows of the same app, most similar titles first."""
    scored = []
    for index, entry in entries.items():
        for window in windows:
            if window.process != entry.get("processo") or window.hwnd in taken:
                continue
            score = difflib.SequenceMatcher(None, normalize(str(entry.get("titulo", ""))), normalize(window.title)).ratio()
            if window.process in FRAME_HOSTS and score < FRAME_HOST_MIN_SIMILARITY:
                continue
            scored.append((score, index, window))
    scored.sort(key=lambda item: item[0], reverse=True)
    matched: dict[int, win_desktop.Window] = {}
    for _score, index, window in scored:
        if index not in matched and window.hwnd not in taken:
            matched[index] = window
            taken.add(window.hwnd)
    return matched


def save_layout(name: str) -> str:
    _require_windows("Salvar layouts")
    label = _layout_label(name)
    if not label or len(label) > 40:
        raise PCControlError("Diga um nome curto para o layout, por exemplo 'trabalho'.")
    screens = win_desktop.monitors()
    items = _placed_windows()
    if not items:
        raise PCControlError("Não há janelas visíveis para salvar.")
    offset = win_desktop.workspace_offset(screens)
    layouts = load_layouts()
    replaced = next((stored for stored in layouts if _layout_key(stored) == normalize(label)), None)
    if replaced is not None:
        del layouts[replaced]
    layouts[label] = {
        "salvo_em": dt.datetime.now().isoformat(timespec="seconds"),
        "janelas": [_layout_entry(window, placement, screen, offset) for window, placement, screen in items],
    }
    _write_layouts(layouts)
    per_screen: dict[int, int] = {}
    for _, _, screen in items:
        per_screen[screen.number] = per_screen.get(screen.number, 0) + 1
    labels = {m.number: m for m in screens}
    spread = ", ".join(
        f"{count} {_on_screen(labels[number]) if number in labels else f'na tela {number}'}"
        for number, count in sorted(per_screen.items())
    )
    again = " (substituí o anterior com esse nome)" if replaced else ""
    return f"Layout '{label}' salvo{again}: {_count(len(items), 'janela')} — {spread}."


def apply_layout(name: str) -> str:
    _require_windows("Aplicar layouts")
    layouts = load_layouts()
    stored = _find_layout(name, layouts)
    entries = {i: e for i, e in enumerate(layouts[stored]["janelas"]) if isinstance(e, dict) and e.get("processo")}
    if not entries:
        raise PCControlError(f"O layout '{stored}' não tem janelas.")
    before = _desktop_windows()
    z_order = {window.hwnd: position for position, window in enumerate(before)}
    taken: set[int] = set()
    matched = _match_layout(entries, before, taken)

    open_processes = {window.process for window in before}
    to_launch: dict[str, str] = {}
    for index, entry in entries.items():
        process, app = entry["processo"], str(entry.get("app") or "")
        if index in matched or process in open_processes or process in to_launch or not app:
            continue
        to_launch[process] = app
    not_opened: list[str] = []
    launched: dict[str, str] = {}
    for process, app in to_launch.items():
        try:
            _label, _target, is_site = resolve_app(app)
            if is_site:
                not_opened.append(f"{app} (não é um app instalado)")
                continue
            launch_app(app)
            launched[process] = app
        except PCControlError as exc:
            not_opened.append(f"{app} ({exc})")
    if launched:
        rest = {i: e for i, e in entries.items() if i not in matched}
        matched.update(_match_layout(rest, _desktop_windows(), taken))
    matched_processes = {entries[i]["processo"] for i in matched}
    opened = [app for process, app in launched.items() if process in matched_processes]
    not_opened += [
        f"{app} (pedi para abrir, mas a janela não apareceu)"
        for process, app in launched.items()
        if process not in matched_processes
    ]

    screens = win_desktop.monitors()
    offset = win_desktop.workspace_offset(screens)
    top_index = min(matched) if matched else None
    moves: list[tuple[int, SavedPosition]] = []
    placed: dict[int, int] = {}
    stuck: list[str] = []
    for index in sorted(matched, reverse=True):  # de baixo para cima: a ordem das janelas fica como foi salva
        entry, window = entries[index], matched[index]
        screen = _layout_screen(entry, screens)
        saved = _remember_position(window.hwnd)
        if saved is not None:
            moves.append((window.hwnd, saved))
        win_desktop.restore_placement(window.hwnd, _layout_placement(entry, screen, offset), focus=index == top_index)
        landed = win_desktop.window_monitor(window.hwnd)
        if landed is not None and landed.number == screen.number:
            placed[screen.number] = placed.get(screen.number, 0) + 1
        else:
            stuck.append(_short_title(window.title))
    moves.sort(key=lambda move: z_order.get(move[0], len(z_order)))
    if moves:
        MEMORY.batch = Batch(f"layout '{stored}'", moves)

    labels = {m.number: m for m in screens}
    total = sum(placed.values())
    spread = ", ".join(f"{count} {_on_screen(labels[number])}" for number, count in sorted(placed.items()))
    parts = [f"Layout '{stored}' aplicado: {_count(total, 'janela')} no lugar" + (f" ({spread})." if spread else ".")]
    if opened:
        parts.append(f"Abri {', '.join(opened)}.")
    if stuck:
        parts.append(f"{_names(stuck)} não {'foi' if len(stuck) == 1 else 'foram'} para o lugar salvo.")
    reported = set(to_launch) - matched_processes  # já aparecem em "Não abri"
    missing = [
        _short_title(str(entries[i].get("titulo") or entries[i]["processo"]))
        for i in entries
        if i not in matched and entries[i]["processo"] not in reported
    ]
    if missing:
        parts.append(
            f"Não encontrei aberta{'s' if len(missing) > 1 else ''}: {_names(missing)} "
            "(não reabro sites, pastas nem janelas extras de um app que já está aberto)."
        )
    if not_opened:
        parts.append(f"Não abri: {'; '.join(not_opened)}.")
    if moves:
        parts.append(UNDO_HINT)
    return " ".join(parts)


def list_layouts() -> str:
    layouts = load_layouts()
    if not layouts:
        return "Nenhum layout salvo ainda. Arrume as janelas e diga, por exemplo, 'salva esse layout como modo trabalho'."
    parts = []
    for stored, data in layouts.items():
        when = ""
        try:
            saved_at = dt.datetime.fromisoformat(str(data.get("salvo_em")))
            when = f", salvo em {saved_at:%d/%m às %H:%M}"
        except ValueError:
            pass
        parts.append(f"'{stored}' ({_count(len(data['janelas']), 'janela')}{when})")
    return "Layouts salvos: " + "; ".join(parts) + "."


def delete_layout(name: str) -> str:
    layouts = load_layouts()
    stored = _find_layout(name, layouts, fuzzy=False)  # apagar só com o nome certo
    del layouts[stored]
    _write_layouts(layouts)
    return f"Layout '{stored}' apagado."


def layouts_action(action: str, name: str | None = None) -> str:
    if action == "list":
        return list_layouts()
    if not (name or "").strip():
        raise PCControlError("Diga o nome do layout, por exemplo 'trabalho'.")
    if action == "save":
        return save_layout(name)  # type: ignore[arg-type]
    if action == "apply":
        return apply_layout(name)  # type: ignore[arg-type]
    if action == "delete":
        return delete_layout(name)  # type: ignore[arg-type]
    raise PCControlError(f"Ação de layout desconhecida: {action}.")


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


def open_in_new_window(label: str, url: str, monitor: int | str) -> str:
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
            f"não movi {_to_screen(screen)} para não levar o HUD junto."
        )
    command = new_window_command(browser, url)
    before = {window.hwnd for window in _desktop_windows()}
    subprocess.Popen(command, creationflags=NO_WINDOW, close_fds=True)  # noqa: S603 — executável e URL validados
    window = _wait_for_browser_window(browser.name.lower(), before)
    if window is None:
        return (
            f"Pedi ao navegador para abrir {label} numa janela nova, mas ela não apareceu em "
            f"{int(SITE_WINDOW_SECONDS)} s, então não a movi {_to_screen(screen)}."
        )
    _remember_opened(window.hwnd, label, host_of(command[-1]))
    return f"Abri {label} numa janela nova do navegador. {_move_window(window, screen)}"


def open_url(label: str, url: str, monitor: int | str | None) -> str:
    """New tab in the current browser window, or a window of its own on `monitor`."""
    if _screen_ref(monitor) is not None:
        return open_in_new_window(label, url, monitor)
    webbrowser.open(url, 2)
    return f"Abri {label} no navegador."


def capture_screen(monitor: int | str | None, window: str | None = None) -> tuple[Any, str]:
    _require_windows("Ler a tela")
    if window:
        target = find_window(window)
        win_desktop.bring_to_front(target.hwnd)
        time.sleep(0.35)  # deixa a janela terminar de redesenhar antes do print
        return win_desktop.grab_region(win_desktop.window_rect(target.hwnd)), f"janela '{target.title}'"
    screen = pick_monitor(monitor) if _screen_ref(monitor) is not None else None
    image = win_desktop.grab_monitor(screen)
    return image, screen.label if screen else "todas as telas"


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
async def open_website(context: RunContext, url: str, monitor: str | None = None) -> str:
    """Open a website in the user's default browser (new tab, or its own window on a monitor).

    Args:
        url: A full URL, a domain ("github.com"), a well-known service name ("Google Maps",
            "Gmail", "Claude", "ChatGPT") or one of the user's saved shortcuts.
            Never invent URLs: if unsure, search_web first and pass the official result URL.
        monitor: Only when the user says where to open it ("abre o YouTube no monitor 1",
            "no notebook"). Screen as the user says it: its number in the Windows Settings ("1", "3") or its
            name ("notebook", "vertical", "de cima", "da esquerda" or a nickname like "tela de código").
            The site then opens in a new browser window moved there, so the HUD's window stays
            put. Don't call manage_window afterwards.
    """
    try:
        label, target = resolve_site(url)
        await net_activity([host_of(target)], "request")
        result = await _run("open_website", label, open_url, label, target, monitor)
        logger.info("Site aberto: %s %s", target, f"(tela: {monitor})" if monitor else "")
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
    monitor: str | None = None,
) -> str:
    """Move, maximize, minimize, focus, snap or close an application window, across monitors.

    The result says the monitor the window really ended up on: report that one.

    Args:
        target: App name or text from the window title, e.g. "Configurações", "Edge", "WhatsApp".
        action: move (to another monitor; needs `monitor`), back (undo the last move/maximize/snap
            and put the window where it was before — "volta pra antiga", "desfaz"), maximize,
            minimize, restore, focus, snap_left, snap_right or close (polite close of that single window).
        monitor: For move/maximize. Screen as the user says it: its number in the Windows Settings ("1", "3") or its
            name ("notebook", "vertical", "de cima", "da esquerda" or a nickname like "tela de código").
            Never guess it for "back".
    """
    try:
        result = await _run("manage_window", target, window_action, target, action, monitor)
        logger.info("Janela: %s %s %s", action, target, monitor or "")
        return result
    except PCControlError as exc:
        return str(exc)


@function_tool()
async def look_at_screen(context: RunContext, monitor: str | None = None, window: str | None = None) -> str:
    """Look at what is on the user's screen. Only when the user explicitly asks to see/read the screen.

    Takes a screenshot, shows it on the HUD and sends it to you as an image so you can
    read and describe it. Prefer `window` when the user names an app (sharper image).

    Args:
        monitor: Screen as the user says it: its number in the Windows Settings ("1", "3") or its
            name ("notebook", "vertical", "de cima", "da esquerda" or a nickname like "tela de código").
            Omit both arguments to capture every monitor.
        window: App or window title to capture alone, e.g. "PhpStorm", "Edge", "WhatsApp".
    """
    detail = window or (f"tela {monitor}" if str(monitor or "").strip().isdigit() else monitor) or "todas as telas"
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


def play_video(query: str, monitor: int | str | None, live: bool = False) -> tuple[dict[str, str] | None, str]:
    """Open the best YouTube match, optionally in its own window on `monitor`.

    Returns (None, "") when nothing matches, so play_youtube decides between the live
    fallback (Twitch) and opening the search page.
    """
    monitor = _screen_ref(monitor)
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
    context: RunContext, query: str, live: bool = False, monitor: str | None = None
) -> str:
    """Search YouTube and open the best matching video or live stream in the browser.

    The result gives the real title and channel and says whether it is live right now.
    Opening a page is not confirmed playback: repeat what the result says.

    Args:
        query: What or who to watch, e.g. "lo-fi para estudar", "trailer Homem de Ferro" or "Gaules".
        live: True when the user asks for a live stream ("a live do…", "ao vivo"). Then only a
            stream that is live right now is opened; if there is none, nothing is opened and the
            result says what to offer instead (e.g. the Twitch channel).
        monitor: Only when the user says where to play it. Screen as the user says it: its number in the Windows Settings ("1", "3") or its
            name ("notebook", "vertical", "de cima", "da esquerda" or a nickname like "tela de código").
            The video opens in its own browser window moved there.
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
    return summary if _screen_ref(monitor) is None else f"{summary} Janela: {placement}"


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
    context: RunContext, service: str, query: str | None = None, monitor: str | None = None
) -> str:
    """Open a streaming/music service, optionally with something to find or play.

    - Spotify + query: tries to really play it in the Spotify desktop app and says whether
      playback was confirmed (otherwise it says it only opened the item or the search).
    - Twitch + query (a channel name): opens that channel and says if it is live, a rerun or offline.
    - Other services only open their search page: nothing starts playing by itself.

    Args:
        service: Netflix, Prime Video, Spotify, Twitch, Globoplay, Disney+, Max, Crunchyroll, Deezer or YouTube.
        query: Optional title, artist, song, show or channel.
        monitor: Only when the user says where to open it. Screen as the user says it: its number in the Windows Settings ("1", "3") or its
            name ("notebook", "vertical", "de cima", "da esquerda" or a nickname like "tela de código").
            The service opens in its own browser window moved there (not for the Spotify app).
    """
    try:
        label, url, searched = streaming_url(service, query)
    except PCControlError as exc:
        return str(exc)
    monitor = _screen_ref(monitor)  # type: ignore[assignment]
    not_moved = (
        f" (Não levei para a tela pedida ({monitor}): isso só vale para sites abertos numa janela nova.)"
        if monitor
        else ""
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
async def open_app(context: RunContext, name: str, monitor: str | None = None) -> str:
    """Open an installed application by name (any app in the Start Menu) and bring its window to the front.

    It checks that a visible window really appeared; report exactly what the result says
    (it may say the app is hidden in the tray or did not open). Never opens installers or uninstallers.

    Args:
        name: App name, e.g. "Spotify", "calculadora", "VS Code", "WhatsApp", "Steam".
        monitor: Only when the user says where to open it. Screen as the user says it: its number in the Windows Settings ("1", "3") or its
            name ("notebook", "vertical", "de cima", "da esquerda" or a nickname like "tela de código").
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


def lock_workstation() -> None:
    """Bloqueia a tela do Windows (também usado pela presença quando o usuário sai)."""
    _require_windows("Bloquear a tela")
    import ctypes

    ctypes.windll.user32.LockWorkStation()


@function_tool()
async def lock_computer(context: RunContext) -> str:
    """Lock the computer screen (the user will need their password to come back)."""
    if not IS_WINDOWS:
        return "Bloquear a tela só está disponível no Windows por enquanto."

    await tool_status("lock_computer", "running")
    lock_workstation()
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


@function_tool()
async def manage_screens(
    context: RunContext,
    action: Literal["list", "nickname", "forget_nickname", "renumber", "confirm"],
    screen: str | None = None,
    name: str | None = None,
    number: int | None = None,
) -> str:
    """See, name and renumber the user's screens (telas/monitores).

    Screens are numbered like the "Identificar" button of the Windows Settings (Sistema > Tela)
    and also have names: "notebook" (built-in screen), "vertical", "de cima", "da esquerda"...
    plus nicknames the user gives. Every tool with `monitor` accepts any of these.

    Args:
        action: list (number, names and nicknames of each screen; also shown on the HUD);
            nickname ("salva a tela vertical como tela de código" → screen="vertical",
            name="tela de código"); forget_nickname (name); renumber when the user says a number
            is wrong ("a tela 1 é o notebook" → screen="notebook", number=1); confirm when the user
            says the numbers match the Windows Settings.
        screen: Which screen, by number or name ("2", "notebook", "de cima", a nickname).
        name: The nickname, for nickname/forget_nickname.
        number: The number the Windows Settings show on that screen, for renumber.
    """
    try:
        result = await _run("manage_screens", name or screen or action, screens_action, action, screen, name, number)
    except PCControlError as exc:
        return str(exc)
    if action == "list":
        screens = await asyncio.to_thread(win_desktop.monitors)
        lines = "\n".join(f"- {line}" for line in win_desktop.describe_monitors(screens).split("; "))
        await show_card("note", {"title": "Telas", "content": lines})
    logger.info("Telas: %s → %s", action, result)
    return result


@function_tool()
async def manage_layouts(
    context: RunContext,
    action: Literal["save", "apply", "list", "delete"],
    name: str | None = None,
) -> str:
    """Save and restore window layouts ("modo trabalho"): which app sits on which screen, and where.

    - save: captures every visible window (app, title, screen, position, maximized) under `name`.
    - apply: reopens the apps that are missing and puts each window back in place ("modo
      trabalho", "ativa o layout estudo"). Sites and folders are not reopened.
    - list / delete.
    After apply, "desfaz" = arrange_windows(action="undo").

    Args:
        action: save, apply, list or delete.
        name: Layout name, e.g. "trabalho" (for "modo trabalho"), "estudo", "jogo".
    """
    try:
        result = await _run("manage_layouts", name or action, layouts_action, action, name)
    except PCControlError as exc:
        return str(exc)
    logger.info("Layouts: %s %s → %s", action, name or "", result)
    return result


@function_tool()
async def arrange_windows(
    context: RunContext,
    action: Literal["gather", "move_all", "show_desktop", "undo"],
    monitor: str | None = None,
    from_monitor: str | None = None,
) -> str:
    """Move or hide many windows at once, and undo it.

    - gather: every window to one screen ("organiza tudo pro notebook" → monitor="notebook").
    - move_all: the windows of one screen to another ("manda tudo do notebook pro monitor de
      cima" → from_monitor="notebook", monitor="de cima").
    - show_desktop: minimize everything ("mostra a área de trabalho").
    - undo: put back every window of the last of these actions or of the last layout applied
      ("desfaz", "volta tudo", "traz as janelas de volta").
    The HUD's browser window is never moved or hidden by these actions.

    Args:
        action: gather, move_all, show_desktop or undo.
        monitor: Destination screen for gather/move_all: number in the Windows Settings or name.
        from_monitor: Source screen for move_all.
    """
    detail = " → ".join(str(item) for item in (from_monitor, monitor) if item) or action
    try:
        result = await _run("arrange_windows", detail, arrange_action, action, monitor, from_monitor)
    except PCControlError as exc:
        return str(exc)
    logger.info("Organizar janelas: %s → %s", action, result)
    return result


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
        manage_screens,
        manage_layouts,
        arrange_windows,
        look_at_screen,
        save_shortcut,
    ]
